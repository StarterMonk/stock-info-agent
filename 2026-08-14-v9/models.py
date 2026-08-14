"""
v7 预测模型（统计与机器学习双轨）：
- 基线：EMA20 偏移外推（必须与模型对比的保底项）
- 主模型：SARIMA(1,1,1) 中位价（statsmodels，收敛失败回退基线）
- 置信区间：滚动波动率 sigma，median ± 1.96 · sigma · sqrt(horizon)
- 方向概率：趋势结构 + 动量 + MACD/RSI 超买超卖 的 logit 合成
"""
import math
import logging

import pandas as pd

import data_layer
from features import technical_snapshot

logger = logging.getLogger(__name__)

MODEL_VERSION = "v7-statistical-v1"
HORIZONS_CHOICE = (5, 10, 20)


def _rolling_volatility(close: pd.Series) -> float:
    value = float(close.tail(20).pct_change().std())
    if value is None or math.isnan(value):
        return 0.005
    return max(value, 0.005)


def _ema_baseline_medians(close: pd.Series, horizons):
    ema = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
    current = float(close.iloc[-1])
    drift = current / ema - 1.0
    return {h: current * (1.0 + drift * h / 20.0) for h in horizons}


def _sarima_forecast(close: pd.Series, horizons):
    try:
        from statsmodels.tsa.statespace.sarimax import SARIMAX
        fitted = SARIMAX(close, order=(1, 1, 1)).fit(
            method_kwargs={"maxiter": 200, "disp": False},
            allow_infrequent=True)
        predicted = fitted.get_forecast(steps=max(horizons)).predicted_mean
        return {h: float(predicted.iloc[h - 1]) for h in horizons}
    except Exception as exc:
        logger.warning("SARIMA 失败，回退 EMA 基线：%s", exc)
        return {}


def _forecast_medians(close: pd.Series, horizons):
    sarima = _sarima_forecast(close, horizons)
    ema = _ema_baseline_medians(close, horizons)
    out = {}
    for horizon in horizons:
        candidate = sarima.get(horizon, ema[horizon])
        if not math.isfinite(candidate) or abs(candidate / ema[horizon] - 1.0) > 0.5:
            candidate = ema[horizon]
        out[horizon] = candidate
    return out


def _band_items(medians: dict, current_price: float, volatility: float):
    return {
        h: {
            "horizon_days": h,
            "median_price": round(medians[h], 2),
            "low_price": round(medians[h] - current_price * 1.96 * volatility * math.sqrt(h), 2),
            "high_price": round(medians[h] + current_price * 1.96 * volatility * math.sqrt(h), 2),
        }
        for h in medians
    }


def _direction_probability(tech: dict) -> float:
    score = 0.0
    if tech.get("trend_state") == "多头":
        score += 1.0
    elif tech.get("trend_state") == "空头":
        score -= 1.0
    score += tech.get("momentum_5d", 0.0) * 30
    score += tech.get("momentum_20d", 0.0) * 8
    score += 0.4 if tech.get("macd_relation") == "金叉" else -0.4
    if tech.get("overbought"):
        score -= 0.6
    elif tech.get("oversold"):
        score += 0.5
    return 1.0 / (1.0 + math.exp(-score))


def price_forecast(code: str, horizons=None) -> dict:
    """主入口：返回完整预测 dict（工具 get_price_prediction 的直接数据源）。"""
    data_layer.initialize_database()
    horizons = tuple(horizons or HORIZONS_CHOICE)
    frame = data_layer.load_history(code, years=3)
    if frame is None or len(frame) < 120:
        return {"code": code, "error": "历史数据不足（需至少 120 个交易日，已尝试自动回填）"}

    tech = technical_snapshot(frame)
    close = frame["close_price"].astype(float).reset_index(drop=True)
    if close.isna().any():
        close = close.ffill().bfill()
    current_price = float(close.iloc[-1])

    medians = _forecast_medians(close, horizons)
    volatility = _rolling_volatility(close)
    band_items = _band_items(medians, current_price, volatility)
    forecasts = [band_items[h] for h in sorted(horizons)]

    probability_up = _direction_probability(tech)
    if probability_up >= 0.55:
        direction = "偏多"
    elif probability_up <= 0.45:
        direction = "偏空"
    else:
        direction = "中性"

    result = {
        "code": code,
        "current_price": round(current_price, 2),
        "direction": direction,
        "direction_score": round(probability_up, 3),
        "support_level": tech.get("support_level"),
        "resistance_level": tech.get("resistance_level"),
        "forecasts": forecasts,
        "trend_summary": {k: tech.get(k) for k in
                          ("trend_state", "macd_relation", "rsi_14", "atr_14",
                           "volume_ratio", "momentum_5d")},
        "model_version": MODEL_VERSION,
        "source": "AKShare(qfq 日线) + v7 统计模型（SARIMA/EMA 基线 + 波动率置信带）",
        "disclaimer": "预测基于历史行情统计推断，不构成投资建议。",
    }
    first = forecasts[0] if forecasts else {}
    data_layer.save_prediction_record({
        "stock_code": code,
        "forecast_date": str(frame["trade_date"].iloc[-1]),
        "horizon_days": first.get("horizon_days", 5),
        "direction_score": round(probability_up, 3),
        "support_level": tech.get("support_level", 0.0) or 0.0,
        "resistance_level": tech.get("resistance_level", 0.0) or 0.0,
        "confidence_low": first.get("low_price", 0.0) or 0.0,
        "confidence_high": first.get("high_price", 0.0) or 0.0,
        "model_version": MODEL_VERSION,
    })
    return result