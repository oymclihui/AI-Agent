"""
ML 进化引擎 · CNN 1D 形态识别（阶段三）

- TinyCNN: Conv1D(1→32,k=5)+ReLU+MaxPool → Conv1D(32→64,k=3)+ReLU+GAP → FC → 4类
- 4类形态: 0=突增(spike_up) 1=突降(spike_down) 2=周期波动(periodic) 3=平稳(stable)
- 弱监督打标: 规则自动打标（滑动窗口斜率 + 单步跳变 + 自相关周期检测）
  标签来源如实标注：规则弱监督，非人工真值，进化仅作辅助参考
- build_tensors: 归一化 + 滑动窗口 + 规则打标 + 时间顺序切分
- train_model / evaluate: CrossEntropy 增量训练；accuracy 在验证集计算
- classify_shape: 对最新窗口推理形态 + 置信度 + 周期检测
- torch 顶层导入（与 lstm_model 一致），Celery 已装 torch 才会走到本模块
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn

torch.set_num_threads(1)  # 与 lstm_model 一致，避免 Celery 抢占

# 形态类别定义
SHAPE_NAMES = {0: "突增", 1: "突降", 2: "周期波动", 3: "平稳"}


class TinyCNN(nn.Module):
    """1D CNN 形态识别: Conv1D×2 + GAP → FC → 4类"""

    def __init__(self, window: int = 30, n_classes: int = 4):
        super().__init__()
        self.conv1 = nn.Conv1d(1, 32, kernel_size=5, padding=2)
        self.pool1 = nn.MaxPool1d(2)
        self.conv2 = nn.Conv1d(32, 64, kernel_size=3, padding=1)
        self.gap = nn.AdaptiveAvgPool1d(1)
        self.fc = nn.Linear(64, n_classes)

    def forward(self, x):  # x: (B, 1, window)
        x = self.pool1(torch.relu(self.conv1(x)))
        x = torch.relu(self.conv2(x))
        x = self.gap(x).squeeze(-1)  # (B, 64)
        return self.fc(x)  # (B, n_classes)


# ────────────────────── 弱监督规则打标 ──────────────────────

def _autocorr(yn: np.ndarray, lag: int) -> float:
    """归一化自相关系数"""
    n = len(yn)
    if n - lag < 3:
        return 0.0
    try:
        return float(np.corrcoef(yn[:-lag], yn[lag:])[0, 1])
    except Exception:
        return 0.0


def detect_period(y_window: np.ndarray) -> Optional[int]:
    """自相关法检测主周期（返回 lag 或 None）"""
    y = np.asarray(y_window, dtype=float)
    n = len(y)
    if n < 10:
        return None
    mean, std = float(y.mean()), float(y.std())
    if std < 1e-9:
        return None
    yn = (y - mean) / std
    best_lag, best_ac = 0, 0.4
    for lag in range(2, n // 3 + 1):
        ac = _autocorr(yn, lag)
        if ac > best_ac:
            best_ac = ac
            best_lag = lag
    return best_lag if best_lag > 0 else None


def auto_label_window(y_window: np.ndarray) -> int:
    """
    规则弱监督打标（如实标注标签来源为规则，非人工真值）：
    0=突增 1=突降 2=周期波动 3=平稳

    判定依据：
    - 单步最大跳变（标准化后）> 1.5σ 且趋势斜率为正/负 → 突增/突降
    - 自相关在 lag 2..n/3 存在显著峰值(>0.4) → 周期波动
    - 以上均不满足 → 平稳
    """
    y = np.asarray(y_window, dtype=float)
    n = len(y)
    if n < 5:
        return 3
    mean, std = float(y.mean()), float(y.std())
    if std < 1e-9:
        return 3
    yn = (y - mean) / std

    # 1. 单步跳变
    diffs = np.diff(yn)
    max_jump = float(np.max(diffs)) if len(diffs) > 0 else 0.0
    min_jump = float(np.min(diffs)) if len(diffs) > 0 else 0.0

    # 2. 趋势斜率（标准化空间）
    t = np.arange(n, dtype=float)
    tvar = float(np.var(t))
    slope = float(np.cov(t, yn)[0, 1] / tvar) if tvar > 1e-9 else 0.0

    # 3. 周期性
    ac_peak, ac_lag = 0.0, 0
    if n >= 10:
        for lag in range(2, n // 3 + 1):
            ac = _autocorr(yn, lag)
            if abs(ac) > abs(ac_peak):
                ac_peak, ac_lag = ac, lag

    SPIKE_THRESH = 1.5   # 标准化单步跳变阈值
    SLOPE_THRESH = 0.03  # 每步斜率阈值（标准化空间）
    AC_THRESH = 0.4      # 自相关周期阈值

    if max_jump > SPIKE_THRESH and slope > SLOPE_THRESH:
        return 0  # 突增
    if min_jump < -SPIKE_THRESH and slope < -SLOPE_THRESH:
        return 1  # 突降
    if abs(ac_peak) > AC_THRESH and ac_lag >= 2:
        return 2  # 周期波动
    return 3  # 平稳


# ────────────────────── 张量构造 ──────────────────────

def build_tensors(ts: Dict[str, Any], window: int = 30, val_ratio: float = 0.2) -> Optional[Dict[str, Any]]:
    """归一化 + 滑动窗口 + 规则打标 + 时间顺序切分；样本/类别不足返回 None"""
    y = np.asarray(ts["y"], dtype=float)
    n = len(y)
    if n < window + 5:
        return None
    mean, std = float(y.mean()), float(y.std())
    if std < 1e-9:
        std = 1.0
    yn = (y - mean) / std

    X, labels = [], []
    for i in range(n - window + 1):
        X.append(yn[i:i + window])
        labels.append(auto_label_window(y[i:i + window]))
    X = np.asarray(X, dtype=np.float32)[:, None, :]  # (n_windows, 1, window)
    labels = np.asarray(labels, dtype=np.int64)

    cut = int(len(X) * (1 - val_ratio))
    if cut < 5 or len(X) - cut < 2:
        return None

    # 训练集至少需要 2 个不同类别才能训练分类器
    unique_train = set(labels[:cut].tolist())
    if len(unique_train) < 2:
        return None

    return {
        "Xtr": torch.tensor(X[:cut]),
        "ytr": torch.tensor(labels[:cut]),
        "Xva": torch.tensor(X[cut:]),
        "yva": torch.tensor(labels[cut:]),
        "last_window": torch.tensor(X[-1:]),
        "scaler_mean": mean,
        "scaler_std": std,
        "n_train": int(cut),
        "n_val": int(len(X) - cut),
        "window": window,
        "n_classes": 4,
        "label_dist": {int(k): int(v) for k, v in zip(*np.unique(labels, return_counts=True))},
    }


# ────────────────────── 训练 / 评估 ──────────────────────

def train_model(model: nn.Module, Xtr: torch.Tensor, ytr: torch.Tensor, epochs: int = 10, lr: float = 1e-3) -> None:
    """增量 fine-tune（CrossEntropy，CPU 秒级）"""
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    lossf = nn.CrossEntropyLoss()
    model.train()
    for _ in range(epochs):
        opt.zero_grad()
        loss = lossf(model(Xtr), ytr)
        loss.backward()
        opt.step()


@torch.no_grad()
def evaluate(model: nn.Module, tensors: Dict[str, Any]) -> Tuple[float, Dict[int, float]]:
    """返回 (accuracy, per_class_accuracy)；验证集为空返回 0"""
    model.eval()
    logits = model(tensors["Xva"])  # (n_val, 4)
    pred = logits.argmax(dim=1)
    yva = tensors["yva"]
    if len(yva) == 0:
        return 0.0, {}
    acc = float((pred == yva).float().mean().item())
    # 各类准确率
    per_class: Dict[int, float] = {}
    for c in range(4):
        mask = (yva == c)
        if mask.sum() > 0:
            per_class[c] = float((pred[mask] == c).float().mean().item())
    return acc, per_class


# ────────────────────── 推理 ──────────────────────

@torch.no_grad()
def classify_shape(
    model: nn.Module,
    ts: Dict[str, Any],
    window: int = 30,
    scaler_mean: Optional[float] = None,
    scaler_std: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """对最新窗口推理形态分类，返回 {label, shape, confidence, period?}"""
    model.eval()
    y = np.asarray(ts["y"], dtype=float)
    n = len(y)
    if n < window:
        return None
    mean = float(scaler_mean) if scaler_mean is not None else float(y.mean())
    std = float(scaler_std) if scaler_std is not None else (float(y.std()) or 1.0)
    yn = (y - mean) / std
    w = yn[-window:]
    x = torch.tensor(w, dtype=torch.float32)[None, None, :]  # (1, 1, window)
    logits = model(x)
    probs = torch.softmax(logits, dim=1)[0]
    label = int(probs.argmax().item())
    conf = float(probs[label].item())

    period = None
    if label == 2:  # 周期波动时检测周期
        period = detect_period(y[-window:])

    return {
        "label": label,
        "shape": SHAPE_NAMES[label],
        "confidence": round(conf, 4),
        "period": period,
    }
