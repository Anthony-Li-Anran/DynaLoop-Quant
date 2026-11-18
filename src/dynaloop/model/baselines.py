"""Sequence baselines using the same input and output contract as the brain."""
import torch
from torch import nn

from dynaloop.model.brain import BrainConfig


class SequenceBaseline(nn.Module):
    def __init__(self, config: BrainConfig, kind: str):
        super().__init__()
        if kind not in {"gru", "transformer"}:
            raise ValueError("unknown baseline")
        self.config, self.kind = config, kind
        with torch.random.fork_rng(devices=[]):
            torch.random.default_generator.manual_seed(config.seed)
            if kind == "gru":
                self.core = nn.GRU(len(config.features), config.width, num_layers=2, batch_first=True)
            else:
                self.embedding = nn.Linear(len(config.features), config.width)
                self.position = nn.Parameter(torch.randn(config.window, config.width) * .02)
                self.core = nn.ModuleList([nn.TransformerEncoderLayer(config.width, config.heads,
                    dim_feedforward=4*config.width, dropout=0., batch_first=True,
                    norm_first=True, activation="gelu") for _ in range(config.blocks * config.loops)])
            self.head = nn.Sequential(nn.LayerNorm(config.width), nn.Linear(config.width, 1))

    def forward(self, x):
        if self.kind == "gru":
            h, _ = self.core(x)
        else:
            h = self.embedding(x) + self.position
            for block in self.core:
                h = block(h)
        return self.head(h[:, -1]).squeeze(-1)
