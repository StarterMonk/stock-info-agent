"""
中等分析方法（用户提示"深度分析"或"详细分析"时使用）：
1. XGBoost 梯度提升
2. LightGBM 梯度提升
3. GARCH 波动率模型
4. 卡尔曼滤波
5. ARIMA 季节模型
"""
import math
import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _build_features(df: pd.DataFrame, target_col: str = "close_price"):
    """构建 ML 特征矩阵。"""
    close = df[target_col].astype(float)
    features = pd.DataFrame(index=df.index)
    features["return_1d"] = close.pct_change()
    features["return_5d"] = close.pct_change(5)
    features["return_20d"] = close.pct_change(20)
    features["ma5_ratio"] = close / close.rolling(5).mean()
    features["ma20_ratio"] = close / close.rolling(20).mean()
    features["vol_5d"] = close.pct_change().rolling(5).std()
    features["vol_20d"] = close.pct_change().rolling(20).std()
    features["rsi"] = _compute_rsi(close, 14)
    features["macd_diff"] = close.ewm(span=12).mean() - close.ewm(span=26).mean()
    features["boll_pos"] = (close - close.rolling(20).mean()) / (close.rolling(20).std() + 1e-8)
    features["volume_ratio"] = df.get("volume_hands", pd.Series(1, index=df.index)).rolling(20).mean()
    # 滞后特征
    for lag in [1, 2, 3, 5]:
        features[f"lag_{lag}"] = close.pct_change(lag)
    return features


def _compute_rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / (loss + 1e-8)
    return 100 - 100 / (1 + rs)


def xgboost_forecast(df: pd.DataFrame, horizons: list) -> dict:
    """XGBoost 梯度提升预测。"""
    try:
        import xgboost as xgb
        from sklearn.model_selection import TimeSeriesSplit

        close = df["close_price"].astype(float).reset_index(drop=True)
        features = _build_features(df).reset_index(drop=True)

        # 构建目标：未来 N 天收益率
        target = close.shift(-1) / close - 1
        valid_mask = features.notna().all(axis=1) & target.notna()
        X = features[valid_mask].values
        y = target[valid_mask].values

        if len(X) < 30:
            return {"method": "XGBoost", "error": "数据不足"}

        model = xgb.XGBRegressor(
            n_estimators=100, max_depth=4, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, random_state=42,
            verbosity=0,
        )
        model.fit(X[:-1], y[:-1])

        # 递归预测
        current = float(close.iloc[-1])
        forecasts = {}
        last_features = features.iloc[-1:].values.copy()

        for h in horizons:
            pred = model.predict(last_features)[0]
            pred = max(-0.1, min(0.1, pred))  # 限制 ±10%
            forecasts[h] = round(current * (1 + pred) ** h, 2)

        return {"method": "XGBoost", "forecasts": forecasts, "current_price": current}
    except Exception as e:
        logger.warning("XGBoost 失败: %s", e)
        return {"method": "XGBoost", "error": str(e)}


def lightgbm_forecast(df: pd.DataFrame, horizons: list) -> dict:
    """LightGBM 梯度提升预测。"""
    try:
        import lightgbm as lgb

        close = df["close_price"].astype(float).reset_index(drop=True)
        features = _build_features(df).reset_index(drop=True)

        target = close.shift(-1) / close - 1
        valid_mask = features.notna().all(axis=1) & target.notna()
        X = features[valid_mask].values
        y = target[valid_mask].values

        if len(X) < 30:
            return {"method": "LightGBM", "error": "数据不足"}

        model = lgb.LGBMRegressor(
            n_estimators=100, num_leaves=31, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, random_state=42,
            verbose=-1,
        )
        model.fit(X[:-1], y[:-1])

        current = float(close.iloc[-1])
        forecasts = {}
        for h in horizons:
            pred = model.predict(features.iloc[-1:].values)[0]
            pred = max(-0.1, min(0.1, pred))
            forecasts[h] = round(current * (1 + pred) ** h, 2)

        return {"method": "LightGBM", "forecasts": forecasts, "current_price": current}
    except Exception as e:
        logger.warning("LightGBM 失败: %s", e)
        return {"method": "LightGBM", "error": str(e)}


def garch_forecast(close: pd.Series, horizons: list) -> dict:
    """GARCH 波动率模型：预测条件方差 + 置信区间。"""
    try:
        from arch import arch_model

        returns = close.pct_change().dropna() * 100  # 百分比收益率
        if len(returns) < 50:
            return {"method": "GARCH", "error": "数据不足"}

        model = arch_model(returns, vol="Garch", p=1, q=1, mean="AR", lags=1)
        fitted = model.fit(disp="off", show_warning=False)

        current = float(close.iloc[-1])
        forecasts = {}

        for h in horizons:
            pred = fitted.forecast(horizon=h)
            # 取中位数（均值回归）
            mean_returns = pred.mean.iloc[-1].values
            cum_return = (1 + mean_returns / 100).prod() - 1
            cum_return = max(-0.2, min(0.2, cum_return))
            forecasts[h] = round(current * (1 + cum_return), 2)

        return {"method": "GARCH", "forecasts": forecasts, "current_price": current}
    except Exception as e:
        logger.warning("GARCH 失败: %s", e)
        return {"method": "GARCH", "error": str(e)}


def kalman_forecast(close: pd.Series, horizons: list) -> dict:
    """卡尔曼滤波：状态空间模型预测趋势。"""
    try:
        values = close.values.astype(float)
        n = len(values)

        # 简单卡尔曼滤波：状态 = [价格, 速度]
        F = np.array([[1, 1], [0, 1]])  # 状态转移
        H = np.array([[1, 0]])          # 观测矩阵
        Q = np.eye(2) * 0.01            # 过程噪声
        R = np.array([[1.0]])           # 观测噪声

        x = np.array([values[0], 0])    # 初始状态
        P = np.eye(2) * 100             # 初始协方差

        for i in range(1, n):
            # 预测
            x_pred = F @ x
            P_pred = F @ P @ F.T + Q
            # 更新
            z = values[i] - H @ x_pred
            S = H @ P_pred @ H.T + R
            K = P_pred @ H.T @ np.linalg.inv(S)
            x = x_pred + K @ z
            P = (np.eye(2) - K @ H) @ P_pred

        current = float(close.iloc[-1])
        velocity = float(x[1])
        acceleration = 0.01  # 轻微加速

        forecasts = {}
        for h in horizons:
            pred = current + velocity * h + 0.5 * acceleration * h**2
            # 限制变动幅度
            max_change = current * 0.05 * h
            pred = max(current - max_change, min(current + max_change, pred))
            forecasts[h] = round(pred, 2)

        return {"method": "卡尔曼滤波", "forecasts": forecasts, "current_price": current}
    except Exception as e:
        logger.warning("卡尔曼滤波失败: %s", e)
        return {"method": "卡尔曼滤波", "error": str(e)}


def arima_seasonal_forecast(close: pd.Series, horizons: list) -> dict:
    """ARIMA 季节模型（SARIMAX）。"""
    try:
        from statsmodels.tsa.statespace.sarimax import SARIMAX

        model = SARIMAX(close, order=(1, 1, 1), seasonal_order=(1, 1, 1, 5))
        fitted = model.fit(disp=False, maxiter=100, show_warning=False)

        current = float(close.iloc[-1])
        pred = fitted.get_forecast(steps=max(horizons))
        mean = pred.predicted_mean

        forecasts = {}
        for h in horizons:
            val = float(mean.iloc[h - 1])
            # 合理性检查
            if abs(val / current - 1) > 0.3:
                val = current  # 偏差过大则回退
            forecasts[h] = round(val, 2)

        return {"method": "ARIMA季节", "forecasts": forecasts, "current_price": current}
    except Exception as e:
        logger.warning("ARIMA 季节模型失败: %s", e)
        return {"method": "ARIMA季节", "error": str(e)}


def run_medium_methods(df: pd.DataFrame, close: pd.Series, horizons: list) -> dict:
    """运行所有中等方法并返回集成结果。"""
    results = {}
    methods = [
        ("xgboost", lambda: xgboost_forecast(df, horizons)),
        ("lightgbm", lambda: lightgbm_forecast(df, horizons)),
        ("garch", lambda: garch_forecast(close, horizons)),
        ("kalman", lambda: kalman_forecast(close, horizons)),
        ("arima_seasonal", lambda: arima_seasonal_forecast(close, horizons)),
    ]

    for name, fn in methods:
        try:
            results[name] = fn()
        except Exception as e:
            logger.warning("中等方法 %s 失败: %s", name, e)
            results[name] = None

    valid = [r for r in results.values() if r and "forecasts" in r]
    if not valid:
        return {"method": "medium_ensemble", "error": "所有中等方法均失败"}

    ensemble = {}
    for h in horizons:
        vals = [r["forecasts"][h] for r in valid if h in r["forecasts"]]
        if vals:
            ensemble[h] = round(float(np.median(vals)), 2)

    return {
        "method": "中等方法集成",
        "individual": {k: v for k, v in results.items() if v},
        "ensemble_forecasts": ensemble,
        "current_price": float(close.iloc[-1]),
        "methods_used": [r["method"] for r in valid],
    }
