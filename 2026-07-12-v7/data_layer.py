"""
v7 数据层：A 股前复权日线拉取、SQLite 持久化与增量更新。

表命名规范：全部使用「英文全称或中文拼音全称」，不用缩写——
  daily_price_history  每日前复权日线价格历史（含开盘/最高/最低/收盘/成交量/成交额）
  prediction_history   预测结果留痕与 TTL 缓存（供图表与审计复用）
"""
import os
import datetime
import logging
import sqlite3

import pandas as pd
import akshare as ak

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "stock_data.db")
ADJUST_TYPE = "qfq"  # A 股必须前复权，否则分红送转会制造虚假的价格断裂
PREDICTION_TTL_SECONDS = 6 * 3600  # 预测结果缓存 6 小时

_conn_instance = None


def _get_connection():
    global _conn_instance
    if _conn_instance is None:
        _conn_instance = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn_instance.execute("PRAGMA journal_mode=WAL")
    return _conn_instance


def initialize_database():
    conn = _get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_price_history(
            stock_code      TEXT NOT NULL,
            trade_date      TEXT NOT NULL,
            open_price      REAL NOT NULL,
            high_price      REAL NOT NULL,
            low_price       REAL NOT NULL,
            close_price     REAL NOT NULL,
            volume_hands    REAL NOT NULL,
            turnover_amount REAL NOT NULL,
            sync_type       TEXT NOT NULL DEFAULT 'qfq',
            PRIMARY KEY (stock_code, trade_date)
        )""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prediction_history(
            stock_code       TEXT NOT NULL,
            forecast_date    TEXT NOT NULL,
            horizon_days     INTEGER NOT NULL,
            direction_score  REAL NOT NULL,
            support_level    REAL NOT NULL,
            resistance_level REAL NOT NULL,
            confidence_low   REAL NOT NULL,
            confidence_high  REAL NOT NULL,
            model_version    TEXT NOT NULL,
            created_at       TEXT NOT NULL,
            PRIMARY KEY (stock_code, forecast_date, horizon_days, model_version)
        )""")
    conn.commit()


def _to_sina_symbol(code: str) -> str:
    if code.startswith(("60", "68", "9", "5", "11", "113", "110")):
        return "sh" + code
    return "sz" + code


def fetch_history_frame(code: str, start_date: str, end_date: str):
    """从 AKShare 拉取前复权日线，返回列名全称的清洗后 DataFrame；为空返回 None。"""
    frame = ak.stock_zh_a_daily(
        symbol=_to_sina_symbol(code),
        start_date=start_date,
        end_date=end_date,
        adjust=ADJUST_TYPE,
    )
    if frame is None or len(frame) == 0:
        return None
    frame = frame.copy()
    frame["trade_date"] = frame["date"].astype(str).str.replace("-", "", regex=False)
    frame = frame.rename(columns={
        "open": "open_price", "high": "high_price", "low": "low_price",
        "close": "close_price", "volume": "volume_hands", "amount": "turnover_amount",
    })
    return frame[["trade_date", "open_price", "high_price", "low_price",
                  "close_price", "volume_hands", "turnover_amount"]]


def backfill(code: str, years: int = 3) -> dict:
    """为单只股票回填/增量合并 years 年 qfq 日线（幂等，可每日收盘后调用）。"""
    today = datetime.date.today()
    start = (today - datetime.timedelta(days=365 * years)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    frame = fetch_history_frame(code, start, end)
    if frame is None or len(frame) == 0:
        return {"stock_code": code, "inserted_rows": 0, "error": "返回为空"}
    rows = list(frame.itertuples(index=False, name=None))
    conn = _get_connection()
    conn.executemany("""
        INSERT OR REPLACE INTO daily_price_history(
            stock_code, trade_date, open_price, high_price, low_price,
            close_price, volume_hands, turnover_amount, sync_type)
        VALUES(?,?,?,?,?,?,?,?,?)""",
        [(code, r[0], r[1], r[2], r[3], r[4], r[5], r[6], ADJUST_TYPE) for r in rows])
    conn.commit()
    return {"stock_code": code, "inserted_rows": len(rows),
            "start_date": start, "end_date": end, "adjust": ADJUST_TYPE}


def load_history(code: str, years: int = 3):
    """读取本地持久化日线（升序）；数据不足 120 条时自动触发回填。"""
    conn = _get_connection()
    frame = pd.read_sql_query(
        "SELECT stock_code, trade_date, open_price, high_price, low_price, "
        "close_price, volume_hands, turnover_amount FROM daily_price_history "
        "WHERE stock_code=? ORDER BY trade_date ASC",
        conn, params=(code,))
    if frame is None or len(frame) < 120:
        backfill(code, years=years)
        frame = pd.read_sql_query(
            "SELECT stock_code, trade_date, open_price, high_price, low_price, "
            "close_price, volume_hands, turnover_amount FROM daily_price_history "
            "WHERE stock_code=? ORDER BY trade_date ASC",
            conn, params=(code,))
    return frame


def save_prediction_record(record: dict) -> None:
    """写一条预测留痕，主键 (code, forecast_date, horizon, model_version)。"""
    conn = _get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO prediction_history(
            stock_code, forecast_date, horizon_days, direction_score,
            support_level, resistance_level, confidence_low, confidence_high,
            model_version, created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (record["stock_code"], record["forecast_date"], record["horizon_days"],
         record["direction_score"], record["support_level"],
         record["resistance_level"], record["confidence_low"],
         record["confidence_high"], record["model_version"],
         datetime.datetime.now().isoformat(timespec="seconds")))
    conn.commit()


def load_prediction_cache(code: str, horizon_days: int, model_version: str):
    """TTL 内命中返回最新预测 dict，否则 None。"""
    conn = _get_connection()
    cursor = conn.execute("""
        SELECT stock_code, forecast_date, horizon_days, direction_score,
               support_level, resistance_level, confidence_low, confidence_high,
               model_version, created_at
        FROM prediction_history
        WHERE stock_code=? AND horizon_days=? AND model_version=?
        ORDER BY created_at DESC LIMIT 1""",
        (code, horizon_days, model_version))
    row = cursor.fetchone()
    if not row:
        return None
    created_at = datetime.datetime.fromisoformat(row[9])
    if (datetime.datetime.now() - created_at).total_seconds() > PREDICTION_TTL_SECONDS:
        return None
    return {
        "code": row[0], "forecast_date": row[1], "horizon": row[2],
        "direction_score": row[3], "support_level": row[4], "resistance": row[5],
        "confidence_low": row[6], "confidence_high": row[7], "model_version": row[8],
    }