"""Real-data, time-split benchmark of the complete neural Wake/Sleep loop.

Run development first; run the locked test only after protocol/code validation.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time

import numpy as np
import torch
from sklearn.linear_model import Ridge

from dynaloop.infrastructure import fingerprint
from dynaloop.model.brain import BrainConfig, LoopedTransformer
from dynaloop.model.baselines import SequenceBaseline
from dynaloop.training_engine.diffusion import ConditionalDiffusion, DiffusionConfig
from dynaloop.training_engine.sequences import FEATURES, CONTEXT, FeatureScaler, sequences
from dynaloop.training_engine.supervised import fit_predictor, predict
from dynaloop.training_engine.wake import WakeConfig, WakeLearner
from dynaloop.training_engine.sleep import SleepConfig, SleepController
from dynaloop.research_engine.strategies import FactorSignalStrategy
from dynaloop.validation_backtesting_engine import BacktestConfig, StaticFeed, run_backtest
from dynaloop.validation_backtesting_engine.strategies import BuyAndHoldStrategy, FlatStrategy


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def design_matrix(x):
    return np.concatenate((x[:, -1], x.mean(axis=1), x.std(axis=1)), axis=1)


def rolling_mean_forecast(data, dates, length=60):
    """Simple online control: use only labels mature BEFORE this prediction."""
    return np.array([float(np.mean(data.y[data.maturity < date][-length:])) for date in dates])


def backtest_metrics(data, dates, values, start, end):
    rows = [r for r in data.records if start <= r["date"] <= end]
    config = BacktestConfig(commission_rate=.0003, min_commission=5., slippage_rate=.0005,
                           lot_size=100., periods_per_year=252, data_frequency="1d")
    feed = StaticFeed.from_records(rows, symbol=data.symbol)
    if isinstance(values, str) and values == "buy_hold":
        strategy = BuyAndHoldStrategy(symbol=data.symbol)
    elif isinstance(values, str) and values == "cash":
        strategy = FlatStrategy()
    else:
        strategy = FactorSignalStrategy(dict(zip(dates, (np.asarray(values)/100).tolist())),
                                        symbol=data.symbol, threshold=.002)
    result = run_backtest(feed, strategy, config)
    return result


def forecast_metrics(prediction, target):
    prediction = np.asarray(prediction, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)
    error = prediction-target
    ic = float(np.corrcoef(prediction, target)[0, 1]) if np.std(prediction) > 1e-10 and np.std(target) > 0 else None
    return dict(mse=float(np.mean(error**2)), mae=float(np.mean(abs(error))), ic=ic,
                direction_accuracy=float(np.mean((prediction > 0) == (target > 0))))


def streaming(data, pretrained, scaler, train_paths, *, start, end, device, seed,
              sleep_enabled, output, replay_only=False, wake_learning_rate=1e-5):
    config = pretrained.config
    wake = WakeConfig(horizon=5, learning_rate=wake_learning_rate, huber_delta=1., target_scale=100.)
    learner = WakeLearner(config, wake, symbol=data.symbol, device=device)
    learner.model.load_state_dict(pretrained.state_dict())
    history_mask = data.maturity < start
    hx, hy = scaler.transform(data.x[history_mask]), data.y[history_mask]
    for x, y in zip(hx[-wake.replay_capacity:], hy[-wake.replay_capacity:]):
        learner.replay.append((torch.tensor(x), float(y)/100))
    controller = None
    if sleep_enabled:
        generator = ConditionalDiffusion(DiffusionConfig(CONTEXT+config.window+wake.horizon, seed=seed), device=device)
        fit = generator.fit(train_paths, updates=400)
        print(data.symbol, seed, "diffusion fit", fit, flush=True)
        controller = SleepController(learner, generator, scaler,
            SleepConfig(synthetic_weight=0. if replay_only else .2), seed=seed)
    first = next(i for i, row in enumerate(data.records) if row["date"] >= start)
    # Prime inputs only: no prediction occurs before the scored interval.
    for i in range(first-config.window+1, first):
        row = data.records[i]
        features = dict(zip(FEATURES, scaler.transform(data.features[i]).tolist()))
        learner.observe(row["date"], row["close"], features, symbol=data.symbol)
    events, predictions = [], {}
    evaluated = 0
    last_attempt = -100000
    for i in range(first, len(data.records)):
        row = data.records[i]
        if row["date"] > end:
            break
        features = dict(zip(FEATURES, scaler.transform(data.features[i]).tolist()))
        if controller:
            event, lineage = controller.observe(row["date"], row["close"], features, symbol=data.symbol)
            learner = controller.learner
        else:
            event, lineage = learner.observe(row["date"], row["close"], features, symbol=data.symbol), 0
        events.append(dict(**asdict(event), lineage=lineage))
        if event.prediction is not None:
            predictions[row["date"]] = event.prediction*100
        evaluated += 1
        if controller and controller.candidate is None and evaluated-last_attempt >= controller.config.interval:
            available = data.maturity <= row["date"]
            paths = data.paths[available][-512:]
            if len(paths) >= 64:
                controller.propose(paths, timestamp=row["date"], max_maturity=str(data.maturity[available][-1]))
                last_attempt = evaluated
        if evaluated % 100 == 0:
            print(data.symbol, seed, "sleep" if sleep_enabled else "wake", evaluated,
                  "lineage", lineage, flush=True)
    output.mkdir(parents=True, exist_ok=True)
    learner.save(output/"incumbent.pt")
    write_json(output/"events.json", events)
    if controller:
        controller.save(output/"checkpoint")
        write_json(output/"sleep.json", controller.checkpoint_metadata())
    return predictions, controller.log if controller else []


def paired_interval(records, control, *, seed=2026):
    # Aggregate correlated seeds/assets by date, then resample contiguous blocks.
    by_date = {}
    for row in records:
        date = row["date"]
        difference = (row[control]-row["target"])**2 - (row["wake_sleep"]-row["target"])**2
        by_date.setdefault(date, []).append(difference)
    values = np.array([np.mean(by_date[d]) for d in sorted(by_date)])
    rng = np.random.default_rng(seed)
    block = min(20, len(values))
    boot = []
    for _ in range(2000):
        starts = rng.integers(len(values)-block+1, size=int(np.ceil(len(values)/block)))
        sample = np.concatenate([values[s:s+block] for s in starts])[:len(values)]
        boot.append(float(sample.mean()))
    return dict(mean_mse_improvement=float(values.mean()),
                interval95=[float(v) for v in np.quantile(boot, [.025, .975])],
                date_count=len(values), block_length=block, replicates=2000)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="experiments/full_loop/data_unadjusted")
    parser.add_argument("--output", required=True)
    parser.add_argument("--phase", choices=("development", "test"), required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--seeds", nargs="+", type=int, default=[7, 17, 29])
    parser.add_argument("--symbols", nargs="+", default=["sh510300", "sh510500", "sz159915"])
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--wake-lr", type=float, default=1e-5)
    args = parser.parse_args(argv)
    output = Path(args.output)
    if (output/"manifest.json").exists():
        raise ValueError("output already contains an experiment; use a new directory")
    if args.device.startswith("cuda") and not torch.cuda.is_available():
        raise ValueError("CUDA unavailable; install compatible PyTorch or explicitly select cpu")
    torch.set_num_threads(2)
    torch.backends.cudnn.benchmark = False
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    begin = time.perf_counter()
    start, end = ("2022-01-01", "2023-12-31") if args.phase == "development" else ("2024-01-01", "2025-12-31")
    datasets, snapshots = {}, {}
    for symbol in args.symbols:
        snapshot = json.loads((Path(args.data)/f"{symbol}.json").read_text(encoding="utf-8"))
        if snapshot.get("synthetic") is not False or fingerprint(snapshot["records"]) != snapshot["fingerprint"]:
            raise ValueError("real snapshot provenance/integrity check failed")
        if any(s["metadata"]["request_param"].split(",")[-1] != "" for s in snapshot["sources"]):
            raise ValueError("benchmark requires verified unadjusted snapshot requests")
        datasets[symbol] = sequences(snapshot["records"], symbol, 32, 5)
        snapshots[symbol] = snapshot["fingerprint"]
    manifest = dict(arguments=vars(args), split=dict(train_end="2021-12-31", validation_start="2022-01-01",
        validation_end="2023-12-31", evaluation_start=start, evaluation_end=end),
        data_fingerprints=snapshots, torch=str(torch.__version__),
        device=torch.cuda.get_device_name() if args.device.startswith("cuda") else "cpu",
        protocol_fingerprint=fingerprint(Path("experiments/full_loop/PROTOCOL.md").read_text(encoding="utf-8")),
        source_fingerprint=fingerprint({str(p):p.read_text(encoding="utf-8")
            for p in sorted(Path("src/dynaloop").rglob("*.py"))}),
        signal_threshold=.002)
    write_json(output/"manifest.json", manifest)
    train_x, train_y, val_x, val_y, train_paths = [], [], [], [], []
    for data in datasets.values():
        tr = data.partition("2016-01-01", "2021-12-31")
        va = data.partition("2022-01-01", "2023-12-31")
        train_x.append(data.x[tr]); train_y.append(data.y[tr]); train_paths.append(data.paths[tr])
        val_x.append(data.x[va]); val_y.append(data.y[va])
    train_x, train_y = np.concatenate(train_x), np.concatenate(train_y)
    val_x, val_y, train_paths = np.concatenate(val_x), np.concatenate(val_y), np.concatenate(train_paths)
    scaler = FeatureScaler.fit(train_x)
    train_x, val_x = scaler.transform(train_x), scaler.transform(val_x)
    write_json(output/"scaler.json", scaler.to_dict())
    ridge_options = []
    for alpha in (1., 10., 100., 1000.):
        ridge = Ridge(alpha=alpha).fit(design_matrix(train_x), train_y)
        ridge_options.append((float(np.mean((ridge.predict(design_matrix(val_x))-val_y)**2)), alpha, ridge))
    _, ridge_alpha, ridge = min(ridge_options, key=lambda row: row[0])
    write_json(output/"ridge.json", dict(alpha=ridge_alpha, coefficient=ridge.coef_.tolist(),
                                        intercept=float(ridge.intercept_)))
    results, all_predictions = [], []
    for seed in args.seeds:
        config = BrainConfig(FEATURES, window=32, width=64, heads=4, blocks=1, loops=3,
                             seed=seed, normalization="none")
        models = {}
        for kind in ("gru", "transformer", "looped"):
            model = (LoopedTransformer(config) if kind == "looped" else SequenceBaseline(config, kind)).to(args.device)
            fit = fit_predictor(model, train_x, train_y, val_x, val_y, seed=seed, epochs=args.epochs)
            modeldir = output/f"seed_{seed}"/kind
            modeldir.mkdir(parents=True, exist_ok=True)
            torch.save(model.state_dict(), modeldir/"pretrained.pt")
            write_json(modeldir/"fit.json", dict(**fit, config=asdict(config),
                parameters=sum(p.numel() for p in model.parameters())))
            print(seed, kind, "selected epoch", fit["selected_epoch"], "validation MSE", fit["validation_mse"], flush=True)
            models[kind] = model
        for symbol, data in datasets.items():
            mask = data.partition(start, end)
            x, y, dates = scaler.transform(data.x[mask]), data.y[mask], data.dates[mask]
            predictions = dict(zero=np.zeros(len(y)), mean=np.full(len(y), float(train_y.mean())),
                rolling_mean=rolling_mean_forecast(data, dates),
                ridge=ridge.predict(design_matrix(x)),
                gru=predict(models["gru"], x), transformer=predict(models["transformer"], x),
                frozen=predict(models["looped"], x))
            for name in ("wake", "wake_replay", "wake_sleep"):
                run_dir = output/f"seed_{seed}"/symbol/name
                started = time.perf_counter()
                scores, sleep_log = streaming(data, models["looped"], scaler, train_paths,
                    start=start, end=end, device=args.device, seed=seed,
                    sleep_enabled=name != "wake", replay_only=name == "wake_replay", output=run_dir,
                    wake_learning_rate=args.wake_lr)
                predictions[name] = np.array([scores[d] for d in dates])
                write_json(run_dir/"runtime.json", dict(seconds=time.perf_counter()-started,
                    sleep_attempts=sum(e["kind"] == "sleep" for e in sleep_log),
                    promotions=sum(e.get("promoted", False) for e in sleep_log)))
            for name, values in predictions.items():
                result = backtest_metrics(data, dates, values, start, end)
                result_path = output/f"seed_{seed}"/symbol/f"{name}_backtest.json"
                write_json(result_path, result.to_dict())
                results.append(dict(seed=seed, symbol=symbol, model=name,
                    signal_active_fraction=float(np.mean(values > .2)),
                    **forecast_metrics(values, y), **result.metrics))
            for name in ("buy_hold", "cash"):
                result = backtest_metrics(data, dates, name, start, end)
                results.append(dict(seed=seed, symbol=symbol, model=name, **result.metrics))
            for i, date in enumerate(dates):
                all_predictions.append(dict(date=str(date), symbol=symbol, seed=seed, target=float(y[i]),
                                           **{k: float(v[i]) for k,v in predictions.items()}))
            write_json(output/"metrics.json", results)
            write_json(output/"predictions.json", all_predictions)
    comparisons = {name: paired_interval(all_predictions, name) for name in
                   ("zero", "mean", "rolling_mean", "ridge", "gru", "transformer", "frozen", "wake", "wake_replay")}
    summary = {}
    for name in sorted(set(r["model"] for r in results)):
        selected = [r for r in results if r["model"] == name]
        summary[name] = {key: float(np.mean([r[key] for r in selected if r.get(key) is not None]))
                        for key in ("mse", "mae", "total_return", "max_drawdown", "sharpe_ratio", "turnover")
                        if any(r.get(key) is not None for r in selected)}
    passed = all(comparisons[name]["mean_mse_improvement"] > 0 for name in ("zero", "mean", "rolling_mean", "ridge", "wake"))
    passed &= comparisons["wake"]["interval95"][0] > 0
    report = dict(phase=args.phase, summary=summary, paired_comparisons=comparisons,
        effectiveness_criteria_met=bool(passed), seconds=time.perf_counter()-begin,
        caution="Development data also selects pretraining epochs; only locked test supports evaluation claims.")
    write_json(output/"report.json", report)
    print(json.dumps(report, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
