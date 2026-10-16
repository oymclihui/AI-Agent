"""
ML 进化引擎 · 进化闭环（阶段二 LSTM + 阶段三 CNN）

- evolve_after_query: 问数后调用——门槛检测 → 增量训练 → 评估择优 → 晋升/留痕（LSTM）
- evolve_cnn_after_query: 问数后 CNN 进化——弱监督打标 → 训练 → 评估择优 → 晋升/留痕
- forecast_with_production: 预测类问数优先走现役 LSTM（回答前同步执行）
- classify_with_production: 时序问数自动附形态判定（现役 CNN 推理，毫秒级）
- torch 延迟导入：数据不足跳过路径无需 torch（旧镜像/ Celery 也能正确留痕）

数据真实性红线：
- 时序行数 < MIN_ROWS 绝不训练，写 log_skipped 留痕
- LSTM 新模型 MAE 未优于现役 → 不晋升，仅记录
- CNN 新模型 accuracy 未优于现役 → 不晋升，仅记录
- CNN 标签来源为规则弱监督打标，如实标注，非人工真值
- 预测永远带置信区间
"""
from __future__ import annotations

import time
from datetime import timedelta
from typing import Any, Dict, List, Optional

from app.core.data_ask.ml_evolution import registry
from app.core.data_ask.ml_evolution.features import extract_timeseries

MIN_ROWS = 60   # 深度模型硬门槛
WINDOW = 14     # LSTM 滑动窗口步数
HORIZON = 7     # 默认预测步数

# CNN 参数
CNN_WINDOW = 30    # CNN 窗口大小
CNN_MIN_ROWS = 60  # CNN 同门槛（与 LSTM 一致）


def _norm_rows(columns: List[str], rows: List[Any]) -> List[dict]:
    """问数结果 rows 兼容 list-of-dict 与 list-of-list 两种形态，统一为 list-of-dict"""
    out: List[dict] = []
    for r in rows or []:
        if isinstance(r, dict):
            out.append(r)
        elif isinstance(r, (list, tuple)):
            out.append({str(columns[i]): r[i] for i in range(min(len(columns), len(r)))})
        else:
            out.append({"value": r})
    return out


# ────────────────────── LSTM 进化闭环（阶段二） ──────────────────────

async def evolve_after_query(data_source_id: str, columns: List[str], rows: List[Any], question: str) -> Dict[str, Any]:
    """问数完成后的 LSTM 进化闭环（Celery 任务内执行）。返回 {evolved, ...}"""
    t0 = time.time()
    try:
        dicts = _norm_rows(columns, rows)
        ts = extract_timeseries(dicts)
        n_rows = len(ts["y"]) if ts else 0
        if ts is None or n_rows < MIN_ROWS:
            note = f"数据不足({n_rows}行 < {MIN_ROWS})，未触发深度模型训练"
            await registry.log_skipped(str(data_source_id), question, note)
            return {"evolved": False, "reason": note}

        # torch/lstm 延迟导入
        import torch  # noqa: F401
        from app.core.data_ask.ml_evolution import lstm_model as LM

        tensors = LM.build_tensors(ts, window=WINDOW)
        if tensors is None or tensors["n_train"] < 10 or tensors["n_val"] < 2:
            note = f"有效窗口样本不足(train={tensors['n_train'] if tensors else 0})，未训练"
            await registry.log_skipped(str(data_source_id), question, note)
            return {"evolved": False, "reason": note}

        prod = await registry.get_production(str(data_source_id), "lstm")
        model = LM.TinyLSTM()
        if prod:
            try:
                ck = torch.load(prod["file_path"], map_location="cpu", weights_only=False)
                model.load_state_dict(ck["state_dict"])
            except Exception:
                pass  # 权重缺失/结构变更 → 冷启动重新训练

        LM.train_model(model, tensors["Xtr"], tensors["ytr"], epochs=4)
        mae, r2, resid = LM.evaluate(model, tensors)

        old_mae = None
        if prod and isinstance(prod.get("metrics"), dict):
            old_mae = prod["metrics"].get("mae")
        promoted = prod is None or old_mae is None or mae < float(old_mae)

        version = None
        if promoted:
            v = await registry.save_new_version(
                str(data_source_id),
                "lstm",
                metrics={"mae": round(mae, 4), "r2": round(r2, 4), "val_rows": tensors["n_val"]},
                trained_rows=n_rows,
            )
            torch.save(
                {
                    "state_dict": model.state_dict(),
                    "scaler_mean": tensors["scaler_mean"],
                    "scaler_std": tensors["scaler_std"],
                    "window": WINDOW,
                    "residuals": resid[:200],
                },
                v["file_path"],
            )
            await registry.promote(v["id"])
            version = v["version"]

        duration_ms = int((time.time() - t0) * 1000)
        await registry.log_training(
            str(data_source_id),
            trigger_query=question,
            sample_rows=n_rows,
            val_mae=round(mae, 4),
            val_r2=round(r2, 4),
            promoted=bool(promoted),
            duration_ms=duration_ms,
            note=None if promoted else f"MAE {mae:.4f} 未优于现役 {old_mae}",
        )
        return {
            "evolved": bool(promoted),
            "version": version,
            "mae": round(mae, 4),
            "old_mae": old_mae,
            "duration_ms": duration_ms,
        }
    except Exception as exc:  # 训练失败不得影响任何业务
        try:
            await registry.log_skipped(str(data_source_id), question, f"训练异常: {str(exc)[:150]}")
        except Exception:
            pass
        return {"evolved": False, "error": str(exc)[:200]}


async def forecast_with_production(
    data_source_id: str,
    columns: List[str],
    rows: List[Any],
    question: str = "",
    horizon: int = HORIZON,
) -> Dict[str, Any]:
    """预测类问数优先走现役 LSTM。返回 {ok, reason?, version?, mae?, answer_section?, chart?}"""
    dicts = _norm_rows(columns, rows)
    ts = extract_timeseries(dicts)
    n_rows = len(ts["y"]) if ts else 0
    if ts is None or n_rows < MIN_ROWS:
        return {"ok": False, "reason": f"数据量不足（时序数据 {n_rows} 行 < {MIN_ROWS} 行），未触发深度模型预测与训练，本次采用经典方法分析"}

    import torch  # noqa: F401
    from app.core.data_ask.ml_evolution import lstm_model as LM

    prod = await registry.get_production(str(data_source_id), "lstm")
    if not prod:
        return {"ok": False, "reason": f"暂无现役 LSTM 模型（时序数据 {n_rows} 行已达标，回答后将于后台训练生成 v1）"}

    try:
        ck = torch.load(prod["file_path"], map_location="cpu", weights_only=False)
    except Exception:
        return {"ok": False, "reason": "现役模型文件不可读，本次采用经典方法分析"}

    model = LM.TinyLSTM()
    try:
        model.load_state_dict(ck["state_dict"])
    except Exception:
        return {"ok": False, "reason": "现役模型结构不匹配，本次采用经典方法分析"}

    win = int(ck.get("window") or WINDOW)
    tensors = LM.build_tensors(ts, window=win)
    if tensors is None:
        return {"ok": False, "reason": f"时序数据不足以构成预测窗口（{n_rows} 行 < 窗口 {win}+10）"}

    fc = LM.forecast(model, tensors, horizon=horizon, residuals=ck.get("residuals"), nonneg=min(ts["y"]) >= 0)

    # 预测日期：按历史平均间隔外推
    dates = ts["dates"]
    delta = (dates[-1] - dates[0]) / max(len(dates) - 1, 1)
    if delta <= timedelta(0):
        delta = timedelta(days=1)
    fc_dates = [dates[-1] + delta * (i + 1) for i in range(len(fc))]

    def _fmt(d):
        return d.strftime("%Y-%m-%d")

    lines = [
        f"**模型进化预测（LSTM v{prod['version']}）**",
        "",
        f"| {_fmt(dates[-1])}(最后实际) | {', '.join(_fmt(d) for d in fc_dates)} |",
        "|---|---|",
        f"| {ts['y'][-1]:.2f} | " + " · ".join(f"{f_['point']:.2f}" for f_ in fc) + " |",
        "",
        f"> 预测区间（95%残差分位）：最低 " + " · ".join(f"{f_['lo']:.2f}" for f_ in fc)
        + "，最高 " + " · ".join(f"{f_['hi']:.2f}" for f_ in fc),
        f"> 现役模型 v{prod['version']} · 验证 MAE={prod.get('metrics', {}).get('mae')} · 训练样本 {prod.get('trained_rows')} 行 · 预测结果仅供参考，非确定结论",
    ]
    answer_section = "\n".join(lines)

    # 图表：历史近30点 + 预测点连成一条折线（前端 ChartRenderer 兼容 {type,labels,values,series}）
    show_n = min(30, len(dates))
    hist_labels = [_fmt(d) for d in dates[-show_n:]]
    hist_vals = [round(float(v), 4) for v in ts["y"][-show_n:]]
    chart = {
        "type": "line",
        "labels": hist_labels + [_fmt(d) for d in fc_dates],
        "values": hist_vals + [round(f_["point"], 4) for f_ in fc],
        "series": f"{ts['value_col']}（含{len(fc)}步预测）",
        "extra": {"forecast_start": len(hist_labels)},
    }
    return {
        "ok": True,
        "version": prod["version"],
        "mae": prod.get("metrics", {}).get("mae"),
        "answer_section": answer_section,
        "chart": chart,
        "forecast": [[_fmt(d), round(f_["point"], 4)] for d, f_ in zip(fc_dates, fc)],
    }


# ────────────────────── CNN 形态识别进化（阶段三） ──────────────────────

async def evolve_cnn_after_query(data_source_id: str, columns: List[str], rows: List[Any], question: str) -> Dict[str, Any]:
    """问数完成后的 CNN 进化闭环（Celery 任务内执行）。返回 {evolved, ...}"""
    t0 = time.time()
    try:
        dicts = _norm_rows(columns, rows)
        ts = extract_timeseries(dicts)
        n_rows = len(ts["y"]) if ts else 0
        if ts is None or n_rows < CNN_MIN_ROWS:
            note = f"CNN数据不足({n_rows}行 < {CNN_MIN_ROWS})，未触发形态识别模型训练"
            await registry.log_skipped(str(data_source_id), question, note)
            return {"evolved": False, "reason": note}

        import torch  # noqa: F401
        from app.core.data_ask.ml_evolution import cnn_model as CM

        tensors = CM.build_tensors(ts, window=CNN_WINDOW)
        if tensors is None or tensors["n_train"] < 5 or tensors["n_val"] < 2:
            note = f"CNN窗口样本不足(train={tensors['n_train'] if tensors else 0})，未训练"
            await registry.log_skipped(str(data_source_id), question, note)
            return {"evolved": False, "reason": note}

        prod = await registry.get_production(str(data_source_id), "cnn")
        model = CM.TinyCNN(window=CNN_WINDOW)
        if prod:
            try:
                ck = torch.load(prod["file_path"], map_location="cpu", weights_only=False)
                model.load_state_dict(ck["state_dict"])
            except Exception:
                pass  # 权重缺失/结构变更 → 冷启动重新训练

        CM.train_model(model, tensors["Xtr"], tensors["ytr"], epochs=10)
        acc, per_class = CM.evaluate(model, tensors)

        old_acc = None
        if prod and isinstance(prod.get("metrics"), dict):
            old_acc = prod["metrics"].get("accuracy")
        promoted = prod is None or old_acc is None or acc > float(old_acc)

        version = None
        if promoted:
            v = await registry.save_new_version(
                str(data_source_id),
                "cnn",
                metrics={"accuracy": round(acc, 4), "val_rows": tensors["n_val"],
                         "label_dist": tensors.get("label_dist", {})},
                trained_rows=n_rows,
            )
            torch.save(
                {
                    "state_dict": model.state_dict(),
                    "scaler_mean": tensors["scaler_mean"],
                    "scaler_std": tensors["scaler_std"],
                    "window": CNN_WINDOW,
                },
                v["file_path"],
            )
            await registry.promote(v["id"])
            version = v["version"]

        duration_ms = int((time.time() - t0) * 1000)
        await registry.log_training(
            str(data_source_id),
            trigger_query=question,
            sample_rows=n_rows,
            val_mae=round(acc, 4),  # 复用 val_mae 列存 accuracy（note 标注 CNN）
            val_r2=None,
            promoted=bool(promoted),
            duration_ms=duration_ms,
            note=f"CNN accuracy={acc:.4f}" + ("" if promoted else f" 未优于现役 {old_acc}") + f" 标签分布={tensors.get('label_dist', {})}",
        )
        return {
            "evolved": bool(promoted),
            "version": version,
            "accuracy": round(acc, 4),
            "old_accuracy": old_acc,
            "duration_ms": duration_ms,
        }
    except Exception as exc:  # 训练失败不得影响任何业务
        try:
            await registry.log_skipped(str(data_source_id), question, f"CNN训练异常: {str(exc)[:150]}")
        except Exception:
            pass
        return {"evolved": False, "error": str(exc)[:200]}


async def classify_with_production(
    data_source_id: str,
    columns: List[str],
    rows: List[Any],
    question: str = "",
) -> Dict[str, Any]:
    """时序问数自动附形态判定（现役 CNN 推理，毫秒级）。
    返回 {ok, answer_section?, shape?, confidence?, version?}
    数据不足或无现役模型时静默返回 {ok: False}，不附加形态判定。
    """
    dicts = _norm_rows(columns, rows)
    ts = extract_timeseries(dicts)
    n_rows = len(ts["y"]) if ts else 0
    if ts is None or n_rows < CNN_WINDOW:
        return {"ok": False}  # 数据不足，静默不附加

    import torch  # noqa: F401
    from app.core.data_ask.ml_evolution import cnn_model as CM

    prod = await registry.get_production(str(data_source_id), "cnn")
    if not prod:
        return {"ok": False}  # 无现役 CNN 模型，静默

    try:
        ck = torch.load(prod["file_path"], map_location="cpu", weights_only=False)
    except Exception:
        return {"ok": False}

    win = int(ck.get("window") or CNN_WINDOW)
    model = CM.TinyCNN(window=win)
    try:
        model.load_state_dict(ck["state_dict"])
    except Exception:
        return {"ok": False}

    result = CM.classify_shape(
        model, ts,
        window=win,
        scaler_mean=ck.get("scaler_mean"),
        scaler_std=ck.get("scaler_std"),
    )
    if result is None:
        return {"ok": False}

    shape = result["shape"]
    conf = result["confidence"]
    period = result.get("period")
    acc = prod.get("metrics", {}).get("accuracy", "N/A")

    lines = [
        f"**序列形态判定（CNN v{prod['version']}）**",
        f"> 当前序列形态：**{shape}**（置信度 {conf:.1%}）",
    ]
    if period:
        lines.append(f"> 检测到周期 ≈ {period} 个时间单位")
    if shape in ("突增", "突降"):
        lines.append(f"> ⚠️ 异常形态预警：序列出现{shape}特征，建议关注后续走势")
    lines.append(f"> 形态识别模型 v{prod['version']} · 验证准确率 {acc} · 标签来源：规则弱监督打标（非人工真值）· 仅供参考")

    return {
        "ok": True,
        "version": prod["version"],
        "answer_section": "\n".join(lines),
        "shape": shape,
        "confidence": conf,
        "period": period,
    }


# ────────────────────── 慢进化：网格搜索（阶段四） ──────────────────────

async def grid_search_evolve(
    data_source_id: str,
    columns: List[str],
    rows: List[Any],
    question: str = "",
) -> Dict[str, Any]:
    """慢进化：小网格结构搜索（hidden x window x epochs），保留最优组合

    与 evolve_after_query 的区别：
    - evolve_after_query: 固定超参(hidden=64, window=14, epochs=4) 增量 fine-tune
    - grid_search_evolve: 遍历 3x3x2=18 组超参，冷启动或 fine-tune，选 MAE 最优

    Called by nightly_retrain Celery task (手动触发或夜间调度)。
    """
    t0 = time.time()
    try:
        dicts = _norm_rows(columns, rows)
        ts = extract_timeseries(dicts)
        n_rows = len(ts["y"]) if ts else 0
        if ts is None or n_rows < MIN_ROWS:
            note = f"全量重训数据不足({n_rows}行 < {MIN_ROWS})，跳过网格搜索"
            await registry.log_skipped(str(data_source_id), question, note)
            return {"evolved": False, "reason": note}

        import torch  # noqa: F401
        from app.core.data_ask.ml_evolution import lstm_model as LM

        prod = await registry.get_production(str(data_source_id), "lstm")

        # 网格搜索空间（3x3x2=18 组合，CPU 可接受）
        grid = [
            {"hidden": h, "window": w, "epochs": e}
            for h in [32, 64, 128]
            for w in [7, 14, 28]
            for e in [4, 8]
        ]

        best = None
        evaluated = 0
        for cfg in grid:
            try:
                tensors = LM.build_tensors(ts, window=cfg["window"])
                if tensors is None or tensors["n_train"] < 10 or tensors["n_val"] < 2:
                    continue
                model = LM.TinyLSTM(hidden=cfg["hidden"])
                if prod:
                    try:
                        ck = torch.load(prod["file_path"], map_location="cpu", weights_only=False)
                        # 仅在 hidden 匹配时加载权重做 fine-tune，否则冷启动
                        if ck.get("hidden", 64) == cfg["hidden"]:
                            model.load_state_dict(ck["state_dict"])
                    except Exception:
                        pass  # 权重缺失/结构变更 -> 冷启动
                LM.train_model(model, tensors["Xtr"], tensors["ytr"], epochs=cfg["epochs"])
                mae, r2, resid = LM.evaluate(model, tensors)
                evaluated += 1
                if best is None or mae < best["mae"]:
                    best = {
                        "mae": mae,
                        "r2": r2,
                        "resid": resid,
                        "config": cfg,
                        "model": model,
                        "tensors": tensors,
                    }
            except Exception:
                continue  # 某组超参失败不影响其他组

        if best is None:
            note = f"网格搜索全部超参组合均失败(evaluated=0/{len(grid)})"
            await registry.log_skipped(str(data_source_id), question, note)
            return {"evolved": False, "reason": note}

        old_mae = None
        if prod and isinstance(prod.get("metrics"), dict):
            old_mae = prod["metrics"].get("mae")
        promoted = prod is None or old_mae is None or best["mae"] < float(old_mae)

        version = None
        if promoted:
            v = await registry.save_new_version(
                str(data_source_id),
                "lstm",
                metrics={
                    "mae": round(best["mae"], 4),
                    "r2": round(best["r2"], 4),
                    "val_rows": best["tensors"]["n_val"],
                    "grid_search": best["config"],
                },
                trained_rows=n_rows,
            )
            torch.save(
                {
                    "state_dict": best["model"].state_dict(),
                    "scaler_mean": best["tensors"]["scaler_mean"],
                    "scaler_std": best["tensors"]["scaler_std"],
                    "window": best["config"]["window"],
                    "hidden": best["config"]["hidden"],
                    "residuals": best["resid"][:200],
                },
                v["file_path"],
            )
            await registry.promote(v["id"])
            version = v["version"]

        duration_ms = int((time.time() - t0) * 1000)
        await registry.log_training(
            str(data_source_id),
            trigger_query=f"[网格搜索] {question}".strip(),
            sample_rows=n_rows,
            val_mae=round(best["mae"], 4),
            val_r2=round(best["r2"], 4),
            promoted=bool(promoted),
            duration_ms=duration_ms,
            note=(
                f"grid_search best={best['config']} evaluated={evaluated}/{len(grid)} "
                + (f"MAE {best['mae']:.4f} 优于现役 {old_mae}" if promoted
                   else f"MAE {best['mae']:.4f} 未优于现役 {old_mae}")
            ),
        )
        return {
            "evolved": bool(promoted),
            "version": version,
            "mae": round(best["mae"], 4),
            "old_mae": old_mae,
            "best_config": best["config"],
            "evaluated": evaluated,
            "total_configs": len(grid),
            "duration_ms": duration_ms,
        }
    except Exception as exc:
        try:
            await registry.log_skipped(str(data_source_id), question, f"网格搜索异常: {str(exc)[:150]}")
        except Exception:
            pass
        return {"evolved": False, "error": str(exc)[:200]}
