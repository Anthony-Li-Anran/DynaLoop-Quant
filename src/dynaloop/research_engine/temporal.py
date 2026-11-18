"""Causal, budgeted formula research with recent feedback and historical replay.

The existing template grammar, factor evaluator and policy updater are reused.
Sleep means retrospective research, not a generative market model. A selected
formula's future evidence is attached by the experiment runner, never by search.
"""
from dataclasses import asdict, dataclass
import json
from pathlib import Path

import numpy as np
from scipy.stats import rankdata

from dynaloop.model.generators import GenerationRequest, TemplateCandidateGenerator
from dynaloop.research_engine.expressions import parse_expression
from dynaloop.research_engine.frame import FactorFrame
from dynaloop.research_engine.exploration import ExplorationPolicy, uniform_policy
from dynaloop.research_engine.spec import fingerprint
from dynaloop.training_engine.updaters import RewardWeightedUpdater


METHODS = ("frozen", "random", "wake", "recent_replay", "wake_sleep", "rolling_all")


@dataclass(frozen=True)
class TemporalConfig:
    horizon: int = 21
    interval: int = 21
    history: int = 504
    validation: int = 252
    warmup: int = 600
    budget: int = 48
    replay_weight: float = .25
    windows: tuple = (5, 10, 20, 60)
    features: tuple = ("open", "high", "low", "close", "volume")

    def __post_init__(self):
        for name in ("horizon", "interval", "history", "validation", "warmup", "budget"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.budget % 2 or (self.history-self.validation)//self.horizon < 10 or self.validation//self.horizon < 10:
            raise ValueError("even budget and at least10 non-overlapping fit/validation samples required")
        if self.warmup < self.history+self.horizon+max(self.windows):
            raise ValueError("warmup must support independent fitting/validation windows")
        if not 0 <= self.replay_weight <= 1:
            raise ValueError("invalid replay weight")


def correlation(x, y, *, ranks=True):
    x, y = np.asarray(x, float), np.asarray(y, float)
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    if len(x) < 8 or np.ptp(x) < 1e-12 or np.ptp(y) < 1e-12:
        return None
    if ranks:
        x, y = rankdata(x), rankdata(y)
    return float(np.corrcoef(x, y)[0, 1])


class FactorTape:
    """Immutable causal factor cache. Only matured labels are passed to search."""
    def __init__(self, records, config=TemporalConfig(), *, generator=None):
        self.config = config
        self.records = [dict(r) for r in records]
        self.dates = [str(r["date"]) for r in records]
        if self.dates != sorted(set(self.dates)):
            raise ValueError("records must have strictly increasing unique dates")
        self.open = np.array([r["open"] for r in records], float)
        self.close = np.array([r["close"] for r in records], float)
        if not (np.isfinite(self.open).all() and np.isfinite(self.close).all()
                and (self.open > 0).all() and (self.close > 0).all()):
            raise ValueError("invalid prices")
        generator = generator or TemplateCandidateGenerator()
        request = GenerationRequest(config.features, config.windows, config.budget)
        self.instances = generator.instances(request)
        self.keys = tuple(sorted({f"template:{t.template}" for t in self.instances}))
        self.groups = np.array([f"template:{t.template}" for t in self.instances])
        frame = FactorFrame(records, columns=config.features)
        self.values = np.column_stack([frame.evaluate(parse_expression(t.expression),
            min_periods=None).to_series().to_numpy() for t in self.instances])
        self.returns = np.diff(np.log(self.close), prepend=np.nan)
        self.identity = fingerprint([t.expression for t in self.instances])

    def targets(self, indices, *, available_at):
        indices = np.asarray(indices, int)
        end = indices+self.config.horizon+1
        if len(indices) and (indices.min() < 0 or end.max() > available_at):
            raise ValueError("attempt to read an immature label")
        return self.open[end]/self.open[indices+1]-1

class TemporalResearch:
    """One independently seeded stream; checkpoint includes RNG and policy."""
    def __init__(self, tape, method="wake_sleep", seed=7):
        if method not in METHODS:
            raise ValueError(f"unknown method {method}")
        self.tape, self.config, self.method, self.seed = tape, tape.config, method, seed
        self.rng = np.random.default_rng(seed)
        self.policy = uniform_policy(tape.keys, exploration_floor=.1)
        self.last_index = -1
        self.total_queries = 0
        self.frozen = None
        self.initialized = False
        self.pending = []
        self.feedback = []

    @staticmethod
    def relationship_alert(feedback):
        """Observed predictor-reward relationship, not a volatility proxy.

        Descriptive reversal flag on disjoint matured forecasts. No false-alarm
        guarantee. Unpromoted proposals are monitored too, preventing silence
        from being mistaken for evidence that the relation is stable.
        """
        if len(feedback) < 12:
            return False
        past = np.array([v["alignment"] for v in feedback[-12:-6]])
        recent = np.array([v["alignment"] for v in feedback[-6:]])
        return bool(past.mean() > 0 and recent.mean() < 0 and
                    recent.mean()+recent.std(ddof=1)/np.sqrt(6) < 0)

    @staticmethod
    def screen(prediction, target, baseline_mean):
        """Predictive improvement screening, not statistical certification.

        Unlike a short-window correlation this scores actual held-out predictions.
        Require improvement over BOTH zero and the fitting-period mean. A two-SE
        penalty discourages uncertain winners; repeated search is still exploratory.
        """
        loss = (prediction-target)**2
        denominator = max(float(np.mean(target**2)), 1e-10)
        margins = []
        for baseline in (0., baseline_mean):
            difference = (target-baseline)**2-loss
            margins.append(float((difference.mean()-2*difference.std(ddof=1)/np.sqrt(len(target)))/denominator))
        return min(margins)

    def windows(self, i):
        c = self.config
        # Anchor to the actual decision grid; the immediately preceding decision's
        # next-open label is not mature until the following bar.
        last = i-int(np.ceil((c.horizon+1)/c.interval))*c.interval
        recent = np.arange(last-(c.history//c.horizon-1)*c.horizon, last+1, c.horizon)
        end = recent[0]-2*c.horizon
        historical = np.arange(end, max(c.windows)-1, -c.horizon)[::-1]
        count = c.history//c.horizon
        memory = historical[-count:]
        if self.method == "wake_sleep" and len(historical) > count:
            memory = historical[np.linspace(0, len(historical)-1, count).astype(int)]
        return recent, memory

    def _evaluate(self, j, recent, memory, i):
        c, t = self.config, self.tape
        validation = recent[-(c.validation//c.horizon):]
        fit = recent[recent+c.horizon+1 < validation[0]]
        x, y = t.values[fit, j], t.targets(fit, available_at=i)
        valid = np.isfinite(x) & np.isfinite(y)
        if valid.sum() < 8 or np.std(x[valid]) < 1e-12:
            return None
        x, y = x[valid], y[valid]
        mean, scale = float(x.mean()), float(x.std())
        z = np.clip((x-mean)/scale, -5, 5)
        slope = float(np.dot(z-z.mean(), y-y.mean())/(np.dot(z-z.mean(), z-z.mean())+4.))
        intercept = float(y.mean()*len(y)/(len(y)+12)-slope*z.mean())
        direction = 1. if slope >= 0 else -1.
        vx, vy = t.values[validation, j], t.targets(validation, available_at=i)
        vm = np.isfinite(vx)
        if vm.sum() < 10:
            return None
        vz, vy = np.clip((vx[vm]-mean)/scale, -5, 5), vy[vm]
        prediction = np.clip(intercept+slope*vz, -.2, .2)
        score = self.screen(prediction, vy, float(y.mean()))
        fresh_score, replay_score, replay_used, replay_reason = score, None, False, "no_memory"
        if memory is not None and len(memory) >= 8:
            mx, my = t.values[memory, j], t.targets(memory, available_at=i)
            mm = np.isfinite(mx)
            if mm.sum() >= 8:
                mz, my = np.clip((mx[mm]-mean)/scale, -5, 5), my[mm]
                old_slope = float(np.dot(mz-mz.mean(), my-my.mean())/(np.dot(mz-mz.mean(), mz-mz.mean())+4.))
                replay_reason = "relationship_conflict"
                if old_slope*slope > 0:
                    blended = (1-c.replay_weight)*slope+c.replay_weight*old_slope
                    proposed = np.clip(intercept+blended*vz, -.2, .2)
                    replay_score = self.screen(proposed, vy, float(y.mean()))
                    replay_reason = "no_recent_improvement"
                    if replay_score > score and np.mean((proposed-vy)**2) < np.mean((prediction-vy)**2):
                        slope, prediction, score = blended, proposed, replay_score
                        replay_used, replay_reason = True, "recent_validation_improved"
        ic = correlation(direction*vx[vm], vy)
        return dict(factor=int(j), expression=t.instances[j].expression,
                    template=t.instances[j].template, mean=mean, scale=scale,
                    slope=slope, intercept=intercept, direction=direction,
                    score=score, validation_ic=ic, replay_ic=None,
                    fresh_score=fresh_score, replay_score=replay_score, replay_used=replay_used,
                    replay_reason=replay_reason, eligible=bool(score > 0),
                    fit_count=len(y), validation_count=len(vy),
                    validation_mse=float(np.mean((prediction-vy)**2)),
                    fit_end=t.dates[int(fit[-1]+c.horizon+1)],
                    validation_start=t.dates[int(validation[0])])

    def step(self, i):
        c, t = self.config, self.tape
        if i < c.warmup or i >= len(t.dates) or i <= self.last_index:
            raise ValueError("decisions must advance after warmup within the tape")
        self.last_index = i
        remaining = []
        for item in self.pending:
            if item["index"]+c.horizon+1 <= i:
                target = float(t.targets([item["index"]], available_at=i)[0])
                self.feedback.append(dict(index=item["index"], prediction=item["prediction"],
                    target=target, alignment=item["prediction"]*target,
                    excess_error=(item["prediction"]-target)**2-target**2))
            else:
                remaining.append(item)
        self.pending = remaining
        recent, memory = self.windows(i)
        replay = self.method in ("recent_replay", "wake_sleep")
        ratio = float(np.std(t.returns[i-62:i+1])/(np.std(t.returns[i-125:i-62])+1e-12))
        volatility_alert = ratio > 2 or ratio < .5
        alert = self.relationship_alert(self.feedback)
        adaptive = self.method in ("wake", "recent_replay", "wake_sleep")
        if alert and adaptive:
            self.policy = self.policy.with_weights({k: .5*v+.5 for k, v in self.policy.weights.items()})
        if self.method == "frozen" and self.initialized:
            candidates, chosen, queries = [], dict(self.frozen) if self.frozen else None, 0
            proposal = chosen
        else:
            count = c.budget//2 if replay else c.budget
            if self.method == "rolling_all":
                indices = np.arange(len(t.instances))
            else:
                probabilities = self.policy.probabilities(t.keys) if adaptive else np.ones(len(t.keys))/len(t.keys)
                indices = [int(self.rng.choice(np.flatnonzero(t.groups == t.keys[int(self.rng.choice(len(t.keys), p=probabilities))]))) for _ in range(count)]
            candidates = [self._evaluate(j, recent, memory if replay else None, i) for j in indices]
            queries = len(indices)*(2 if replay else 1)
            valid = [v for v in candidates if v is not None]
            proposal = max(valid, key=lambda v: v["score"]) if valid else None
            chosen = proposal if proposal is not None and proposal["eligible"] else None
            if adaptive and valid and any(v["eligible"] for v in valid):
                self.policy = RewardWeightedUpdater().update(self.policy,
                    [f"template:{v['template']}" for v in valid],
                    [float(np.clip(v["score"], -1, 1)) for v in valid])
            elif adaptive:
                # Normalizing negative rewards would still concentrate on a
                # least-bad loser. With no evidence, restore exploration instead.
                self.policy = self.policy.with_weights({k:.95*v+.05 for k,v in self.policy.weights.items()})
            if self.method == "frozen":
                self.frozen = chosen
                self.initialized = True
        self.total_queries += queries
        prediction = 0.
        if chosen is not None and np.isfinite(t.values[i, chosen["factor"]]):
            prediction = float(np.clip(chosen["intercept"]+chosen["slope"]*
                np.clip((t.values[i, chosen["factor"]]-chosen["mean"])/chosen["scale"], -5, 5), -.2, .2))
        if proposal and np.isfinite(t.values[i, proposal["factor"]]):
            proposed = float(np.clip(proposal["intercept"]+proposal["slope"]*
                np.clip((t.values[i, proposal["factor"]]-proposal["mean"])/proposal["scale"], -5, 5), -.2, .2))
            self.pending.append(dict(index=i, prediction=proposed))
        return dict(index=i, date=t.dates[i], method=self.method, selected=chosen,
            proposal=proposal, status="provisional" if chosen else "insufficient_evidence",
            research_indices=recent.tolist(),
            prediction=prediction, queries=queries, total_queries=self.total_queries,
            candidates=candidates, policy=self.policy.to_dict(), drift_alert=alert,
            volatility_ratio=ratio, volatility_alert=volatility_alert,
            matured_feedback=len(self.feedback), label_cutoff=t.dates[int(recent[-1]+c.horizon+1)],
            replay_window=[t.dates[int(memory[0])], t.dates[int(memory[-1]+c.horizon+1)]] if replay and len(memory) else None)

    def save(self, path):
        state = dict(schema_version=2, config=asdict(self.config), method=self.method,
            seed=self.seed, catalog=self.tape.identity, last_index=self.last_index,
            prefix=fingerprint(self.tape.records[:self.last_index+1]),
            policy=self.policy.to_dict(), rng=self.rng.bit_generator.state,
            total_queries=self.total_queries, frozen=self.frozen, initialized=self.initialized,
            pending=self.pending, feedback=self.feedback)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix+".tmp")
        temp.write_text(json.dumps(state, allow_nan=False), encoding="utf-8")
        temp.replace(path)

    @classmethod
    def restore(cls, tape, path):
        state = json.loads(Path(path).read_text(encoding="utf-8"))
        if state["schema_version"] != 2 or state["catalog"] != tape.identity or fingerprint(state["config"]) != fingerprint(asdict(tape.config)):
            raise ValueError("checkpoint schema/config/catalog mismatch")
        if state["prefix"] != fingerprint(tape.records[:state["last_index"]+1]):
            raise ValueError("historical data changed")
        result = cls(tape, state["method"], state["seed"])
        policy = dict(state["policy"])
        policy.pop("schema_version")
        result.policy = ExplorationPolicy(**policy)
        result.rng.bit_generator.state = state["rng"]
        result.last_index, result.total_queries, result.frozen = state["last_index"], state["total_queries"], state["frozen"]
        result.initialized, result.pending, result.feedback = state["initialized"], state["pending"], state["feedback"]
        return result
