"""
复杂分析方法（用户要求"高级分析"/"深度学习"/"AI预测"时使用）：
1. LSTM 长短期记忆网络
2. 简化 Transformer 注意力模型
3. 多模型集成投票
"""
import math
import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _prepare_lstm_data(close: pd.Series, lookback: int = 60):
    """准备 LSTM 序列数据。"""
    values = close.values.astype(np.float32)
    # 标准化
    mean = values.mean()
    std = values.std() + 1e-8
    normalized = (values - mean) / std

    X, y = [], []
    for i in range(lookback, len(normalized)):
        X.append(normalized[i - lookback:i])
        y.append(normalized[i])
    return np.array(X), np.array(y), mean, std


def lstm_forecast(close: pd.Series, horizons: list) -> dict:
    """LSTM 长短期记忆网络预测。"""
    try:
        import torch
        import torch.nn as nn

        lookback = min(60, len(close) - 20)
        if lookback < 20:
            return {"method": "LSTM", "error": "数据不足"}

        X, y, mean, std = _prepare_lstm_data(close, lookback)
        if len(X) < 30:
            return {"method": "LSTM", "error": "数据不足"}

        # 定义 LSTM 模型
        class StockLSTM(nn.Module):
            def __init__(self):
                super().__init__()
                self.lstm = nn.LSTM(1, 32, num_layers=2, batch_first=True, dropout=0.1)
                self.fc = nn.Linear(32, 1)

            def forward(self, x):
                out, _ = self.lstm(x)
                return self.fc(out[:, -1, :])

        model = StockLSTM()
        criterion = nn.MSELoss()
        optimizer = torch.optim.Adam(model.parameters(), lr=0.001)

        # 训练
        X_tensor = torch.FloatTensor(X).unsqueeze(-1)
        y_tensor = torch.FloatTensor(y).unsqueeze(-1)

        model.train()
        for epoch in range(50):
            optimizer.zero_grad()
            pred = model(X_tensor)
            loss = criterion(pred, y_tensor)
            loss.backward()
            optimizer.step()

        # 预测
        model.eval()
        current_seq = torch.FloatTensor(
            (close.values[-lookback:].astype(np.float32) - mean) / std
        ).unsqueeze(0).unsqueeze(-1)

        current = float(close.iloc[-1])
        forecasts = {}

        with torch.no_grad():
            for h in horizons:
                # 递归预测 h 步
                seq = current_seq.clone()
                for _ in range(h):
                    pred = model(seq)
                    seq = torch.cat([seq[:, 1:, :], pred.unsqueeze(1)], dim=1)
                pred_val = float(pred.item()) * std + mean
                # 限制幅度
                max_change = current * 0.05 * h
                pred_val = max(current - max_change, min(current + max_change, pred_val))
                forecasts[h] = round(pred_val, 2)

        return {"method": "LSTM", "forecasts": forecasts, "current_price": current}
    except Exception as e:
        logger.warning("LSTM 失败: %s", e)
        return {"method": "LSTM", "error": str(e)}


def transformer_forecast(close: pd.Series, horizons: list) -> dict:
    """简化 Transformer 注意力模型预测。"""
    try:
        import torch
        import torch.nn as nn

        lookback = min(60, len(close) - 20)
        if lookback < 20:
            return {"method": "Transformer", "error": "数据不足"}

        values = close.values.astype(np.float32)
        mean = values.mean()
        std = values.std() + 1e-8
        normalized = (values - mean) / std

        X, y = [], []
        for i in range(lookback, len(normalized)):
            X.append(normalized[i - lookback:i])
            y.append(normalized[i])
        X, y = np.array(X), np.array(y)

        if len(X) < 30:
            return {"method": "Transformer", "error": "数据不足"}

        class StockTransformer(nn.Module):
            def __init__(self):
                super().__init__()
                self.embed = nn.Linear(1, 16)
                self.attn = nn.MultiheadAttention(16, num_heads=4, batch_first=True)
                self.fc = nn.Sequential(nn.Linear(16, 8), nn.ReLU(), nn.Linear(8, 1))

            def forward(self, x):
                x = self.embed(x)
                x, _ = self.attn(x, x, x)
                return self.fc(x[:, -1, :])

        model = StockTransformer()
        criterion = nn.MSELoss()
        optimizer = torch.optim.Adam(model.parameters(), lr=0.001)

        X_tensor = torch.FloatTensor(X).unsqueeze(-1)
        y_tensor = torch.FloatTensor(y).unsqueeze(-1)

        model.train()
        for epoch in range(50):
            optimizer.zero_grad()
            pred = model(X_tensor)
            loss = criterion(pred, y_tensor)
            loss.backward()
            optimizer.step()

        model.eval()
        current_seq = torch.FloatTensor(
            (close.values[-lookback:].astype(np.float32) - mean) / std
        ).unsqueeze(0).unsqueeze(-1)

        current = float(close.iloc[-1])
        forecasts = {}

        with torch.no_grad():
            for h in horizons:
                seq = current_seq.clone()
                for _ in range(h):
                    pred = model(seq)
                    seq = torch.cat([seq[:, 1:, :], pred.unsqueeze(1)], dim=1)
                pred_val = float(pred.item()) * std + mean
                max_change = current * 0.05 * h
                pred_val = max(current - max_change, min(current + max_change, pred_val))
                forecasts[h] = round(pred_val, 2)

        return {"method": "Transformer", "forecasts": forecasts, "current_price": current}
    except Exception as e:
        logger.warning("Transformer 失败: %s", e)
        return {"method": "Transformer", "error": str(e)}


def run_complex_methods(close: pd.Series, horizons: list) -> dict:
    """运行所有复杂方法并返回集成结果。"""
    results = {}
    methods = [
        ("lstm", lambda: lstm_forecast(close, horizons)),
        ("transformer", lambda: transformer_forecast(close, horizons)),
    ]

    for name, fn in methods:
        try:
            results[name] = fn()
        except Exception as e:
            logger.warning("复杂方法 %s 失败: %s", name, e)
            results[name] = None

    valid = [r for r in results.values() if r and "forecasts" in r]
    if not valid:
        return {"method": "complex_ensemble", "error": "所有复杂方法均失败"}

    ensemble = {}
    for h in horizons:
        vals = [r["forecasts"][h] for r in valid if h in r["forecasts"]]
        if vals:
            ensemble[h] = round(float(np.median(vals)), 2)

    return {
        "method": "复杂方法集成",
        "individual": {k: v for k, v in results.items() if v},
        "ensemble_forecasts": ensemble,
        "current_price": float(close.iloc[-1]),
        "methods_used": [r["method"] for r in valid],
    }
