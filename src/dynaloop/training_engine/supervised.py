"""Shared supervised fit/predict helpers; selection sees validation only."""
from copy import deepcopy

import numpy as np
import torch
from torch.nn import functional as F


@torch.no_grad()
def predict(model, x: np.ndarray, batch_size: int = 256) -> np.ndarray:
    model.eval()
    device = next(model.parameters()).device
    if not len(x):
        return np.empty(0, dtype=np.float32)
    return np.concatenate([model(torch.as_tensor(x[i:i+batch_size], device=device)).cpu().numpy()
                           for i in range(0, len(x), batch_size)])


def fit_predictor(model, train_x, train_y, val_x, val_y, *, seed: int, epochs: int = 20,
                  batch_size: int = 128, learning_rate: float = 3e-4):
    if not len(train_x) or not len(val_x):
        raise ValueError("training and validation samples are required")
    device = next(model.parameters()).device
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=.01)
    rng = np.random.default_rng(seed)
    # A zero output is a legitimate early-stopping candidate, not a hidden test baseline.
    torch.nn.init.zeros_(model.head[-1].weight)
    torch.nn.init.zeros_(model.head[-1].bias)
    best, best_epoch = float(np.mean((predict(model, val_x)-val_y)**2)), 0
    state = deepcopy(model.state_dict())
    history = [dict(epoch=0, validation_mse=best)]
    for epoch in range(1, epochs+1):
        model.train()
        order = rng.permutation(len(train_x))
        losses = []
        for offset in range(0, len(order), batch_size):
            idx = order[offset:offset+batch_size]
            x = torch.as_tensor(train_x[idx], device=device)
            y = torch.as_tensor(train_y[idx], device=device)
            loss = F.huber_loss(model(x), y, delta=1.)
            if not torch.isfinite(loss):
                raise FloatingPointError("nonfinite pretraining loss")
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1., error_if_nonfinite=True)
            optimizer.step()
            losses.append(float(loss.detach()))
        error = float(np.mean((predict(model, val_x)-val_y)**2))
        history.append(dict(epoch=epoch, train_huber=float(np.mean(losses)), validation_mse=error))
        if error < best:
            best, best_epoch, state = error, epoch, deepcopy(model.state_dict())
        if epoch-best_epoch >= 6:
            break
    model.load_state_dict(state)
    return dict(selected_epoch=best_epoch, validation_mse=best, history=history)
