"""
ML 进化引擎 · 轻量 LSTM（PyTorch CPU）：秒级增量训练 + 残差分位置信区间（阶段二）

- TinyLSTM: 输入(滑动窗口,1) → LSTM(64,2层) → Linear → 下一步预测
- build_tensors: 归一化 + 滑动窗口 + 按时间顺序切分训练/验证集
- train_model / evaluate: MSE 增量 fine-tune；MAE/R² 在原始尺度计算
- forecast: 迭代预测 horizon 步，区间 = 残差 5%/95% 分位（数据真实性：永远带区间）
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn

torch.set_num_threads(1)  # Celery concurrency=4，避免抢占


class TinyLSTM(nn.Module):
    def __init__(self, n_features: int = 1, hidden: int = 64):
        super().__init__()
        self.lstm = nn.LSTM(n_features, hidden, num_layers=2, batch_first=True, dropout=0.1)
        self.head = nn.Linear(hidden, 1)

    def forward(self, x):  # x: (B, window, 1)
        out, _ = self.lstm(x)
        return self.head(out[:, -1, :])


def build_tensors(ts: Dict[str, Any], window: int = 14, val_ratio: float = 0.2) -> Optional[Dict[str, Any]]:
    """归一化 + 滑动窗口 + 时间顺序切分；样本不足返回 None"""
    y = np.asarray(ts["y"], dtype=float)
    n = len(y)
    if n < window + 10:
        return None
    mean, std = float(y.mean()), float(y.std())
    if std < 1e-9:
        std = 1.0
    yn = (y - mean) / std

    X, Y = [], []
    for i in range(n - window):
        X.append(yn[i:i + window])
        Y.append(yn[i + window])
    X = np.asarray(X, dtype=np.float32)[:, :, None]
    Y = np.asarray(Y, dtype=np.float32)

    cut = int(len(X) * (1 - val_ratio))
    if cut < 5 or len(X) - cut < 2:
        return None
    return {
        "Xtr": torch.tensor(X[:cut]),
        "ytr": torch.tensor(Y[:cut]),
        "Xva": torch.tensor(X[cut:]),
        "yva": torch.tensor(Y[cut:]),
        "last_window": torch.tensor(X[-1:]),
        "scaler_mean": mean,
        "scaler_std": std,
        "n_train": int(cut),
        "n_val": int(len(X) - cut),
        "window": window,
    }


def train_model(model: nn.Module, Xtr: torch.Tensor, ytr: torch.Tensor, epochs: int = 4, lr: float = 1e-3) -> None:
    """增量 fine-tune（全批小数据，CPU 秒级）"""
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    lossf = nn.MSELoss()
    model.train()
    for _ in range(epochs):
        opt.zero_grad()
        loss = lossf(model(Xtr).squeeze(-1), ytr)
        loss.backward()
        opt.step()


@torch.no_grad()
def _predict_norm(model: nn.Module, X: torch.Tensor) -> np.ndarray:
    model.eval()
    return model(X).squeeze(-1).numpy()


def evaluate(model: nn.Module, tensors: Dict[str, Any]) -> Tuple[float, float, List[float]]:
    """返回 (mae, r2, 残差列表)，均在原始尺度"""
    pred_n = _predict_norm(model, tensors["Xva"])
    mean, std = tensors["scaler_mean"], tensors["scaler_std"]
    yva = tensors["yva"].numpy() * std + mean
    pred = pred_n * std + mean
    resid = (yva - pred).tolist()
    if len(yva) == 0:
        return 0.0, 0.0, resid
    mae = float(np.mean(np.abs(yva - pred)))
    ss_res = float(np.sum((yva - pred) ** 2))
    ss_tot = float(np.sum((yva - yva.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-9 and len(yva) > 1 else 0.0
    return mae, r2, resid


@torch.no_grad()
def forecast(
    model: nn.Module,
    tensors: Dict[str, Any],
    horizon: int = 7,
    residuals: Optional[List[float]] = None,
    nonneg: bool = True,
) -> List[Dict[str, float]]:
    """迭代预测 horizon 步；区间 = 残差 5%/95% 分位（历史残差不足时用 ±2σ 近似）"""
    model.eval()
    mean, std = tensors["scaler_mean"], tensors["scaler_std"]
    seq = tensors["last_window"].clone()
    pts_norm: List[float] = []
    for _ in range(horizon):
        p = float(model(seq).squeeze().item())
        pts_norm.append(p)
        seq = torch.cat([seq[:, 1:, :], torch.tensor([[[p]]], dtype=seq.dtype)], dim=1)
    pts = [v * std + mean for v in pts_norm]

    res = np.asarray(residuals or [], dtype=float)
    if len(res) >= 10:
        lo_q, hi_q = float(np.quantile(res, 0.05)), float(np.quantile(res, 0.95))
    else:
        sigma = float(np.std(res)) if len(res) else abs(mean) * 0.1
        lo_q, hi_q = -2.0 * sigma, 2.0 * sigma
    out = []
    for p in pts:
        lo = p + lo_q
        if nonneg:
            lo = max(lo, 0.0)
        out.append({"lo": lo, "point": p, "hi": p + hi_q})
    return out
