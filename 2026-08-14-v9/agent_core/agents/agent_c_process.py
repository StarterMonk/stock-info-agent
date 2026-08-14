"""
Agent C：数据处理智能体。
三类分析方法：
- 简单（默认）：MA/EMA/BOLL/线性回归/季节分解
- 中等（"深度分析"/"详细分析"）：XGBoost/LightGBM/GARCH/卡尔曼/ARIMA
- 复杂（"AI预测"/"高级分析"/"深度学习"）：LSTM/Transformer/集成

流程：异常检测 → 数据清洗 → 选择方法 → 运行 → LLM 验证
"""
import logging
import re
import datetime
import math

import pandas as pd
import numpy as np

import llm_client
import data_layer
from features import indicator_frame, technical_snapshot
from models_simple import run_simple_methods
from models_medium import run_medium_methods
from models_complex import run_complex_methods
from models import _direction_probability

logger = logging.getLogger(__name__)


def agent_c_process_node(state: dict) -> dict:
    """
    主处理流程：
    1. 异常检测
    2. 数据清洗
    3. 根据复杂度选择方法运行
    4. LLM 验证

    如果数据不足，返回 needs_more_data + data_requests 让 Agent A 补数据。
    """
    raw_data = state.get("raw_data", {})
    ticker = state.get("ticker", "")
    anomaly_resolutions = state.get("anomaly_resolutions", {})
    complexity = state.get("complexity", "simple")
    retry_count = state.get("c_retry_count", 0)

    if not ticker:
        return {"processed_data": {}, "prediction": {}, "current_step": "agent_c_done"}

    # 检查是否需要补充数据（仅首次检查，补数据后不再检查）
    if retry_count == 0:
        insufficient = _check_data_insufficiency(raw_data, ticker, complexity)
        if insufficient:
            return {
                "needs_more_data": True,
                "data_requests": insufficient,
                "c_retry_count": 1,
                "current_step": "needs_more_data",
            }

    # 1. 异常检测
    anomalies = _detect_anomalies(raw_data, ticker)
    unresolved = [a for a in anomalies if a["id"] not in anomaly_resolutions]

    if unresolved and not state.get("anomaly_resolutions"):
        return {
            "anomaly_flags": anomalies,
            "current_step": "anomaly_detected",
        }

    # 2. 加载历史数据并清洗
    processed = _process_data(raw_data, ticker, anomaly_resolutions)

    # 3. 根据复杂度运行预测
    prediction = _run_prediction_by_complexity(ticker, processed, complexity)

    # 4. LLM 验证预测结果
    if prediction and "error" not in prediction:
        validation = _llm_validate(ticker, prediction, processed)
        if validation.get("adjusted"):
            prediction = validation.get("adjusted_prediction", prediction)

    return {
        "processed_data": processed,
        "prediction": prediction,
        "anomaly_flags": anomalies,
        "needs_more_data": False,
        "c_retry_count": 0,
        "current_step": "agent_c_done",
    }


def _check_data_insufficiency(raw_data: dict, ticker: str, complexity: str) -> list:
    """检查数据是否充足，返回需要补充的数据请求列表。"""
    requests = []
    min_days = {"simple": 60, "medium": 100, "complex": 120}
    required = min_days.get(complexity, 60)

    # 检查历史数据
    history = raw_data.get("get_history", {})
    if not isinstance(history, dict) or "error" in history or history.get("count", 0) < required:
        import datetime  # noqa: F811 — local scope for clarity
        years = 3 if complexity in ("medium", "complex") else 2
        start = (datetime.date.today() - datetime.timedelta(days=years * 365)).strftime("%Y%m%d")
        end = datetime.date.today().strftime("%Y%m%d")
        requests.append({"tool": "get_history", "args": {"code": ticker, "start_date": start, "end_date": end}})

    # 复杂方法可能需要分钟线
    if complexity == "complex" and not raw_data.get("get_intraday"):
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        requests.append({"tool": "get_intraday", "args": {"code": ticker, "date": today_str}})

    return requests


def _detect_anomalies(raw_data: dict, ticker: str) -> list:
    """规则化异常检测。"""
    anomalies = []
    anomaly_id = 0

    history = raw_data.get("get_history", {})
    if not isinstance(history, dict) or "error" in history:
        return anomalies

    data = history.get("data", [])
    if not data:
        return anomalies

    # 检测零值
    for d in data:
        close = d.get("close", 0)
        volume = d.get("volume", 0)
        if close == 0 or volume == 0:
            anomalies.append({
                "id": f"zero_{anomaly_id}",
                "type": "zero_value",
                "date": d.get("date", ""),
                "field": "close" if close == 0 else "volume",
                "description": f"{d.get('date', '')} 收盘价为零" if close == 0 else f"{d.get('date', '')} 成交量为零",
                "severity": "high",
                "default_action": "forward_fill",
            })
            anomaly_id += 1

    # 检测涨跌幅异常
    for i in range(1, len(data)):
        prev_close = float(data[i - 1].get("close", 0))
        curr_close = float(data[i].get("close", 0))
        if prev_close > 0:
            ret = abs(curr_close / prev_close - 1.0)
            if ret > 0.10:
                anomalies.append({
                    "id": f"limit_{anomaly_id}",
                    "type": "extreme_return",
                    "date": data[i].get("date", ""),
                    "return_pct": round(ret * 100, 2),
                    "description": f"{data[i].get('date', '')} 涨跌幅 {ret*100:.1f}% 超过 10% 限制",
                    "severity": "medium",
                    "default_action": "cap_at_limit",
                })
                anomaly_id += 1

    # 检测数据缺口
    if len(data) >= 2:
        dates = [d.get("date", "") for d in data]
        gaps = _detect_date_gaps(dates)
        for gap in gaps:
            anomalies.append({
                "id": f"gap_{anomaly_id}",
                "type": "data_gap",
                "start_date": gap["start"],
                "end_date": gap["end"],
                "missing_days": gap["days"],
                "description": f"{gap['start']}~{gap['end']} 缺失 {gap['days']} 个交易日",
                "severity": "medium" if gap["days"] <= 5 else "high",
                "default_action": "forward_fill",
            })
            anomaly_id += 1

    return anomalies


def _detect_date_gaps(dates: list) -> list:
    """检测交易日缺口。"""
    gaps = []
    for i in range(1, len(dates)):
        try:
            d1 = datetime.datetime.strptime(dates[i - 1], "%Y%m%d")
            d2 = datetime.datetime.strptime(dates[i], "%Y%m%d")
            delta = (d2 - d1).days
            if delta > 5:
                gaps.append({
                    "start": dates[i - 1],
                    "end": dates[i],
                    "days": delta - 2,
                })
        except (ValueError, TypeError):
            continue
    return gaps


def _process_data(raw_data: dict, ticker: str, resolutions: dict) -> dict:
    """清洗数据并计算特征。"""
    processed = {}

    try:
        data_layer.initialize_database()
        frame = data_layer.load_history(ticker, years=3)
        if frame is not None and len(frame) >= 60:
            frame = _apply_resolutions(frame, resolutions)
            snapshot = technical_snapshot(frame)
            processed["indicators"] = snapshot
            processed["data_points"] = len(frame)
            processed["latest_date"] = str(frame["trade_date"].iloc[-1])
    except Exception as e:
        logger.warning("Agent C 数据处理失败: %s", e)
        processed["error"] = str(e)

    processed["raw_summary"] = {
        k: {"ok": True} if isinstance(v, dict) and "error" not in v else {"error": v.get("error", "")}
        for k, v in raw_data.items()
        if isinstance(v, dict)
    }

    return processed


def _apply_resolutions(frame: pd.DataFrame, resolutions: dict) -> pd.DataFrame:
    """根据用户对异常的处理决定清洗数据。"""
    if not resolutions:
        return frame

    df = frame.copy()
    for anomaly_id, choice in resolutions.items():
        if choice == "interpolate":
            numeric_cols = df.select_dtypes(include=["number"]).columns
            df[numeric_cols] = df[numeric_cols].interpolate(method="linear")
        elif choice == "forward_fill":
            df = df.ffill()
    return df


def _run_prediction_by_complexity(ticker: str, processed: dict, complexity: str) -> dict:
    """根据复杂度选择方法运行预测。"""
    try:
        data_layer.initialize_database()
        frame = data_layer.load_history(ticker, years=3)
        if frame is None or len(frame) < 60:
            return {"code": ticker, "error": "历史数据不足"}

        close = frame["close_price"].astype(float).reset_index(drop=True)
        if close.isna().any():
            close = close.ffill().bfill()

        horizons = [5, 10, 20]
        current_price = float(close.iloc[-1])

        # 技术指标（所有复杂度都计算）
        tech = technical_snapshot(frame)

        if complexity == "simple":
            result = run_simple_methods(close, horizons)
        elif complexity == "medium":
            result = run_medium_methods(frame, close, horizons)
        elif complexity == "complex":
            # 先运行中等方法作为基础
            base = run_medium_methods(frame, close, horizons)
            advanced = run_complex_methods(close, horizons)
            # 集成：中等 + 复杂方法的中位数
            all_forecasts = {}
            for h in horizons:
                vals = []
                if base and "ensemble_forecasts" in base and h in base["ensemble_forecasts"]:
                    vals.append(base["ensemble_forecasts"][h])
                if advanced and "ensemble_forecasts" in advanced and h in advanced["ensemble_forecasts"]:
                    vals.append(advanced["ensemble_forecasts"][h])
                if vals:
                    all_forecasts[h] = round(float(np.median(vals)), 2)
            result = {
                "method": "中等+复杂方法集成",
                "ensemble_forecasts": all_forecasts,
                "current_price": current_price,
                "base_method": base.get("method", ""),
                "advanced_method": advanced.get("method", ""),
            }
        else:
            result = run_simple_methods(close, horizons)

        # 组装最终预测结果
        ensemble = result.get("ensemble_forecasts", {})
        if not ensemble:
            return {"code": ticker, "error": "预测失败：无有效结果"}

        # 方向概率
        direction_score = _direction_probability(tech)
        if direction_score >= 0.55:
            direction = "偏多"
        elif direction_score <= 0.45:
            direction = "偏空"
        else:
            direction = "中性"

        return {
            "code": ticker,
            "current_price": round(current_price, 2),
            "direction": direction,
            "direction_score": round(direction_score, 3),
            "support_level": tech.get("support_level"),
            "resistance_level": tech.get("resistance_level"),
            "forecasts": [
                {"horizon_days": h, "median_price": ensemble[h]}
                for h in sorted(ensemble.keys())
            ],
            "complexity": complexity,
            "method_used": result.get("method", ""),
            "methods_used": result.get("methods_used", []),
            "individual": result.get("individual", {}),
            "trend_summary": {k: tech.get(k) for k in
                              ("trend_state", "macd_relation", "rsi_14", "atr_14",
                               "volume_ratio", "momentum_5d")},
            "source": f"AKShare + {result.get('method', '未知方法')}",
            "disclaimer": "预测基于历史统计推断，不构成投资建议。",
        }
    except Exception as e:
        logger.error("Agent C 预测失败: %s", e)
        return {"code": ticker, "error": f"预测失败：{e}"}


def _llm_validate(ticker: str, prediction: dict, processed: dict) -> dict:
    """用 LLM 验证预测结果是否合理。"""
    if not llm_client.has_api_key():
        return {"adjusted": False}

    direction = prediction.get("direction", "")
    score = prediction.get("direction_score", 0.5)
    support = prediction.get("support_level")
    resistance = prediction.get("resistance_level")
    current = prediction.get("current_price", 0)
    method = prediction.get("method_used", "")

    prompt = (
        f"请验证以下股票预测结果是否合理（{ticker}）：\n"
        f"- 当前价格：{current}\n"
        f"- 预测方向：{direction}（上涨概率 {score}）\n"
        f"- 支撑位：{support}\n"
        f"- 压力位：{resistance}\n"
        f"- 使用方法：{method}\n"
        f"- 技术状态：{processed.get('indicators', {}).get('trend_state', '未知')}\n\n"
        f"请判断是否合理。如果不合理，返回 JSON：{{'adjusted': true, 'direction': '...', 'support': ..., 'resistance': ...}}\n"
        f"如果合理，返回：{{'adjusted': false}}。"
    )

    try:
        result = llm_client.chat(
            system_prompt="你是金融数据分析专家，负责验证预测结果的合理性。",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=256,
        )
        content = result.get("content", "")

        import json
        match = re.search(r"\{.*\}", content, re.S)
        if match:
            validation = json.loads(match.group(0))
            if validation.get("adjusted"):
                adj = validation
                if "direction" in adj:
                    prediction["direction"] = adj["direction"]
                if "support" in adj:
                    prediction["support_level"] = adj["support"]
                if "resistance" in adj:
                    prediction["resistance_level"] = adj["resistance"]
                return {"adjusted": True, "adjusted_prediction": prediction}
    except Exception as e:
        logger.warning("LLM 验证失败（忽略）：%s", e)

    return {"adjusted": False}
