"""Conditional DDPM for return paths; generated labels are never historical labels.

Standard epsilon-prediction DDPM with a cosine schedule (Ho et al., 2020;
Nichol & Dhariwal, 2021). Small numerical-path denoiser, independent of the brain.
"""
from dataclasses import asdict, dataclass
import math

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from dynaloop.training_engine.sequences import CONTEXT


@dataclass(frozen=True)
class DiffusionConfig:
    length: int
    steps: int = 32
    width: int = 128
    learning_rate: float = 1e-3
    seed: int = 7

    def __post_init__(self):
        if self.length <= CONTEXT or self.steps < 2 or self.width < 1:
            raise ValueError("invalid diffusion dimensions")
        if not math.isfinite(self.learning_rate) or self.learning_rate <= 0:
            raise ValueError("invalid diffusion learning rate")


class ConditionalDiffusion:
    def __init__(self, config: DiffusionConfig, *, device: str = "cpu"):
        self.config, self.device = config, torch.device(device)
        self.rng = torch.Generator(device=self.device).manual_seed(config.seed)
        with torch.random.fork_rng(devices=[]):
            torch.random.default_generator.manual_seed(config.seed)
            self.net = nn.Sequential(nn.Linear(config.length + 16, config.width), nn.SiLU(),
                nn.Linear(config.width, config.width), nn.SiLU(),
                nn.Linear(config.width, config.length - CONTEXT)).to(self.device)
        self.optimizer = torch.optim.AdamW(self.net.parameters(), lr=config.learning_rate)
        time = torch.linspace(0, config.steps, config.steps + 1, device=self.device) / config.steps
        ab = torch.cos((time + .008) / 1.008 * math.pi / 2).square()
        ab = ab / ab[0]
        self.beta = (1 - ab[1:] / ab[:-1]).clamp(max=.999)
        self.alpha = 1 - self.beta
        self.alpha_bar = self.alpha.cumprod(0)
        self.scale = None
        self.bound = None
        self.updates = 0

    def _noise(self, shape):
        return torch.randn(shape, generator=self.rng, device=self.device)

    def _predict(self, x, context, t):
        freq = torch.exp(torch.arange(8, device=self.device) * (-math.log(10000) / 7))
        angle = t[:, None].float() * freq[None]
        embedding = torch.cat((angle.sin(), angle.cos()), dim=1)
        return self.net(torch.cat((x, context, embedding), dim=1))

    def fit(self, paths: np.ndarray, *, updates: int = 300, batch_size: int = 64) -> dict:
        paths = np.asarray(paths, dtype=np.float32)
        if paths.ndim != 2 or paths.shape[1] != self.config.length or not np.isfinite(paths).all() or len(paths) < 2:
            raise ValueError("invalid real diffusion training paths")
        if self.scale is None:
            self.scale = max(float(paths.std()), .05)
            self.bound = min(50., max(3., float(np.quantile(np.abs(paths), .999)) * 2))
        values = torch.as_tensor(paths / self.scale, device=self.device)
        losses = []
        self.net.train()
        for _ in range(updates):
            idx = torch.randint(len(values), (batch_size,), generator=self.rng, device=self.device)
            context, clean = values[idx, :CONTEXT], values[idx, CONTEXT:]
            t = torch.randint(self.config.steps, (batch_size,), generator=self.rng, device=self.device)
            noise = self._noise(clean.shape)
            ab = self.alpha_bar[t, None]
            noisy = ab.sqrt() * clean + (1-ab).sqrt() * noise
            loss = F.mse_loss(self._predict(noisy, context, t), noise)
            if not torch.isfinite(loss):
                raise FloatingPointError("nonfinite diffusion loss")
            self.optimizer.zero_grad(set_to_none=True)
            loss.backward()
            nn.utils.clip_grad_norm_(self.net.parameters(), 1., error_if_nonfinite=True)
            self.optimizer.step()
            losses.append(float(loss.detach()))
        self.updates += updates
        return dict(updates=self.updates, mean_noise_loss=float(np.mean(losses)), scale=self.scale, bound=self.bound)

    @torch.no_grad()
    def sample(self, contexts: np.ndarray) -> tuple[np.ndarray, dict]:
        if self.scale is None:
            raise ValueError("fit diffusion before sampling")
        contexts = np.asarray(contexts, dtype=np.float32)
        if contexts.ndim != 2 or contexts.shape[1] != CONTEXT or not np.isfinite(contexts).all():
            raise ValueError("invalid diffusion context")
        condition = torch.as_tensor(contexts / self.scale, device=self.device)
        x = self._noise((len(contexts), self.config.length - CONTEXT))
        self.net.eval()
        for step in reversed(range(self.config.steps)):
            t = torch.full((len(contexts),), step, device=self.device, dtype=torch.long)
            eps = self._predict(x, condition, t)
            ab = self.alpha_bar[step]
            previous = self.alpha_bar[step-1] if step else torch.ones((), device=self.device)
            # Reconstruct x0 then apply the DDPM posterior mean and variance.
            x0 = ((x - (1-ab).sqrt()*eps) / ab.sqrt()).clamp(-self.bound/self.scale, self.bound/self.scale)
            mean = self.beta[step]*previous.sqrt()/(1-ab)*x0 + (1-previous)*self.alpha[step].sqrt()/(1-ab)*x
            variance = self.beta[step] * (1-previous) / (1-ab)
            x = mean + variance.sqrt()*self._noise(x.shape) if step else mean
        tail = x.cpu().numpy() * self.scale
        paths = np.concatenate((contexts, tail), axis=1)
        valid = np.isfinite(paths).all(axis=1) & (np.abs(paths).max(axis=1) <= self.bound)
        # Reject degenerate or extreme volatility; do not silently clip labels.
        vol = tail.std(axis=1)
        valid &= (vol > .05*self.scale) & (vol < 4*self.scale)
        return paths[valid], dict(requested=len(paths), accepted=int(valid.sum()),
            rejected=int((~valid).sum()), generated_std=float(tail.std()), real_scale=self.scale,
            std_ratio=float(tail.std()/self.scale))

    def state_dict(self):
        return dict(format_version=1, config=asdict(self.config), net=self.net.state_dict(), optimizer=self.optimizer.state_dict(),
                    scale=self.scale, bound=self.bound, updates=self.updates, rng=self.rng.get_state(),
                    rng_device=self.device.type)

    @classmethod
    def from_state_dict(cls, state, *, device="cpu"):
        if state["format_version"] != 1:
            raise ValueError("unsupported diffusion checkpoint")
        result = cls(DiffusionConfig(**state["config"]), device=device)
        if state["rng_device"] != result.device.type:
            raise ValueError("diffusion RNG resume requires the original CPU/CUDA backend")
        result.net.load_state_dict(state["net"])
        result.optimizer.load_state_dict(state["optimizer"])
        result.scale, result.bound, result.updates = state["scale"], state["bound"], state["updates"]
        result.rng.set_state(state["rng"].cpu())
        return result
