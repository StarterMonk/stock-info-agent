"""
v4 工具层：覆盖「目标股票」的全部 AKShare 信息维度，供 Agent 以 function calling 方式调用。

维度清单（每个维度一个工具函数 + 一个 functionDeclaration schema）：
1. get_profile        公司资料 / 上市板块 / 主营业务 / 行业        ✅ AKShare(cninfo)
2. get_history        历史日 K 线（开/收/高/低/量）               ✅ AKShare(新浪日线)
3. get_intraday       盘中分时（分钟级）                          ✅ AKShare(新浪分钟线)
4. get_financials     三大财务报表（资产负债/利润/现金流）         ✅ AKShare(新浪财报)
5. get_dividend       分红送配方案                                ✅ AKShare(cninfo)
6. get_capital_flow   个股资金流向（主力/散户）                   ⚠️ 东方财富接口被代理拦截
7. get_indicators     估值与财务指标（每股收益/每股净资产等）      ✅ AKShare(财务分析指标)
8. get_key_metrics    主要财务指标摘要（营收/净利/增长率）         ✅ AKShare(同花顺摘要)
9. get_forecast       业绩报告/预告（按报告期）                   ✅ AKShare(东方财富业绩报表)

说明：
- 对 ⚠️ 被网络拦截的接口（get_capital_flow），按用户要求「API 调用位置先留空」，
  并在函数内给出明确不可用说明；同时已通过联网检索确认替代方案（见函数注释）。
- 所有工具函数返回「可 JSON 序列化」的 dict，便于回传给 LLM 与前端渲染。
"""
import re
import time as _time
import concurrent.futures
import logging
import akshare as ak

logger = logging.getLogger(__name__)

_TIMEOUT = 15  # seconds

# TTL 缓存：key -> (result, expiry_time)
_cache = {}


def _cached(fn, ttl_seconds, *args, **kwargs):
    """Cache wrapper with TTL. Returns cached result if within TTL, else calls fn."""
    key = (fn.__name__,) + args + tuple(sorted(kwargs.items()))
    now = _time.time()
    if key in _cache:
        result, expiry = _cache[key]
        if now < expiry:
            return result
    result = fn(*args, **kwargs)
    # Only cache successful results (not error dicts)
    if isinstance(result, dict) and "error" not in result:
        _cache[key] = (result, now + ttl_seconds)
    return result


def _with_timeout(fn, *args, **kwargs):
    """Execute fn with a timeout; return error dict on timeout or exception."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fn, *args, **kwargs)
        try:
            return future.result(timeout=_TIMEOUT)
        except concurrent.futures.TimeoutError:
            return {"error": f"查询超时（{_TIMEOUT}s）"}

# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
_LOCAL_NAME_MAP = {
    "贵州茅台": "600519", "茅台": "600519", "贵州茅台酒": "600519",
    "宁德时代": "300750", "比亚迪": "002594", "中国平安": "601318",
    "招商银行": "600036", "五粮液": "000858", "隆基绿能": "601012",
    "东方财富": "300059", "中信证券": "600030", "工商银行": "601398",
}


def _sina_symbol(code):
    if code.startswith(("60", "68", "9", "5", "11", "113", "110")):
        return "sh" + code
    return "sz" + code


def _board_from_code(code):
    if code.startswith("688"):
        return "科创板"
    if code.startswith("60"):
        return "沪市主板"
    if code.startswith(("000", "001", "002", "003")):
        return "深市主板"
    if code.startswith("30"):
        return "创业板"
    if code.startswith(("8", "4")):
        return "北交所"
    return "未知"


def _df_to_records(df, limit=50):
    if df is None or len(df) == 0:
        return []
    recs = df.tail(limit).to_dict(orient="records")
    out = []
    for r in recs:
        out.append({str(k): _jsonable(v) for k, v in r.items()})
    return out


def _jsonable(v):
    import datetime as _dt
    if isinstance(v, (_dt.date, _dt.datetime)):
        return v.isoformat()
    if hasattr(v, "item"):  # numpy 类型
        try:
            return v.item()
        except Exception:
            return str(v)
    return v


# ---------------------------------------------------------------------------
# 1. 公司资料 / 上市详情
# ---------------------------------------------------------------------------
def get_profile(code: str) -> dict:
    """获取目标股票的上市板块、所属行业、主营业务、成立/上市日期等公司资料。"""
    cache_key = ("get_profile", code)
    now = _time.time()
    if cache_key in _cache:
        result, expiry = _cache[cache_key]
        if now < expiry:
            return result
    try:
        df = _with_timeout(ak.stock_profile_cninfo, symbol=code)
        if isinstance(df, dict) and "error" in df:
            return df
        if df is None or len(df) == 0:
            return {"code": code, "error": "未获取到上市详情：返回为空"}
        r = df.iloc[0]
        result = {
            "code": code,
            "name": str(r.get("A股简称", r.get("公司名称", code))),
            "full_name": str(r.get("公司名称", "")),
            "board": _board_from_code(code),
            "market": str(r.get("所属市场", "")),
            "industry": str(r.get("所属行业", "未获取到")),
            "main_business": str(r.get("主营业务", "未获取到")),
            "found_date": str(r.get("成立日期", "未获取到")),
            "list_date": str(r.get("上市日期", "未获取到")),
            "source": "AKShare（巨潮资讯网 cninfo）",
        }
        _cache[cache_key] = (result, now + 86400)  # TTL 24 hours
        return result
    except Exception as e:
        return {"code": code, "error": f"未获取到上市详情：{e}"}


# ---------------------------------------------------------------------------
# 2. 历史日 K 线
# ---------------------------------------------------------------------------
def get_history(code: str, start_date: str = None, end_date: str = None, limit: int = 200) -> dict:
    """获取目标股票历史日线行情（开盘/收盘/最高/最低/成交量），默认返回近一年数据。日期格式 YYYYMMDD。"""
    import datetime as _dt
    if not end_date:
        end_date = _dt.date.today().strftime("%Y%m%d")
    if not start_date:
        start_date = (_dt.date.today() - _dt.timedelta(days=365)).strftime("%Y%m%d")
    try:
        sym = _sina_symbol(code)
        df = _with_timeout(ak.stock_zh_a_daily, symbol=sym, start_date=start_date, end_date=end_date)
        if isinstance(df, dict) and "error" in df:
            return df
        df = df.copy()
        df["date"] = df["date"].astype(str).str.replace("-", "", regex=False)
        df = df[(df["date"] >= start_date) & (df["date"] <= end_date)]
        # Limit rows, keeping the most recent
        original_len = len(df)
        if len(df) > limit:
            df = df.tail(limit)
        recs = [{
            "date": str(r["date"]), "open": _jsonable(r["open"]),
            "close": _jsonable(r["close"]), "high": _jsonable(r["high"]),
            "low": _jsonable(r["low"]), "volume": _jsonable(r["volume"]),
        } for _, r in df.iterrows()]
        return {"code": code, "start_date": start_date, "end_date": end_date,
                "count": len(recs), "data": recs, "truncated": original_len > limit,
                "source": "AKShare（新浪财经日线）"}
    except Exception as e:
        return {"code": code, "error": f"未获取到历史行情：{e}"}


# ---------------------------------------------------------------------------
# 3. 盘中分时
# ---------------------------------------------------------------------------
def get_intraday(code: str, date: str, time: str = None) -> dict:
    """获取目标股票指定日期的分时（分钟级）行情；time 形如 '14:00' 可定位到具体分钟。"""
    try:
        sym = _sina_symbol(code)
        df = _with_timeout(ak.stock_zh_a_minute, symbol=sym, period="1", adjust="")
        if isinstance(df, dict) and "error" in df:
            return df
        df = df.copy()
        df["day"] = df["day"].astype(str)
        day_rows = df[df["day"].str.startswith(date)].copy()
        if time:
            hhmm = time.replace(":", "")
            day_rows["hhmm"] = day_rows["day"].str.extract(r"(\d{2}):(\d{2}):\d{2}$").agg("".join, axis=1)
            match = day_rows[day_rows["hhmm"] == hhmm]
            if len(match) == 0:
                match = day_rows.tail(1)
            rows = match
        else:
            rows = day_rows
        recs = [{
            "time": str(r["day"]), "open": _jsonable(r["open"]),
            "close": _jsonable(r["close"]), "high": _jsonable(r["high"]),
            "low": _jsonable(r["low"]), "volume": _jsonable(r["volume"]),
        } for _, r in rows.iterrows()]
        return {"code": code, "date": date, "time": time, "count": len(recs),
                "data": recs, "source": "AKShare（新浪财经分钟线）"}
    except Exception as e:
        return {"code": code, "error": f"未获取到盘中行情：{e}"}


# ---------------------------------------------------------------------------
# 4. 三大财务报表
# ---------------------------------------------------------------------------
def get_financials(code: str, report_type: str = "资产负债表") -> dict:
    """获取目标股票的三大财务报表之一：资产负债表 / 利润表 / 现金流量表。"""
    cache_key = ("get_financials", code, report_type)
    now = _time.time()
    if cache_key in _cache:
        result, expiry = _cache[cache_key]
        if now < expiry:
            return result
    try:
        sym = _sina_symbol(code)
        df = _with_timeout(ak.stock_financial_report_sina, stock=sym, symbol=report_type)
        if isinstance(df, dict) and "error" in df:
            return df
        result = {"code": code, "report_type": report_type, "count": len(df),
                "columns": list(df.columns)[:30],
                "data": _df_to_records(df, limit=20),
                "source": "AKShare（新浪财经财务报表）"}
        _cache[cache_key] = (result, now + 604800)  # TTL 7 days
        return result
    except Exception as e:
        return {"code": code, "error": f"未获取到财务报表：{e}"}


# ---------------------------------------------------------------------------
# 5. 分红送配
# ---------------------------------------------------------------------------
def get_dividend(code: str) -> dict:
    """获取目标股票的历史分红送配方案（派息/送股/转增/股权登记日等）。"""
    cache_key = ("get_dividend", code)
    now = _time.time()
    if cache_key in _cache:
        result, expiry = _cache[cache_key]
        if now < expiry:
            return result
    try:
        df = _with_timeout(ak.stock_dividend_cninfo, symbol=code)
        if isinstance(df, dict) and "error" in df:
            return df
        result = {"code": code, "count": len(df),
                "data": _df_to_records(df, limit=20),
                "source": "AKShare（巨潮资讯网 cninfo）"}
        _cache[cache_key] = (result, now + 604800)  # TTL 7 days
        return result
    except Exception as e:
        return {"code": code, "error": f"未获取到分红方案：{e}"}


# ---------------------------------------------------------------------------
# 6. 个股资金流向  ⚠️ 东方财富接口被代理拦截
# ---------------------------------------------------------------------------
def get_capital_flow(code: str, market: str = None) -> dict:
    """
    获取目标股票个股资金流向（主力/散户净流入）。

    ⚠️ 当前网络环境：ak.stock_individual_fund_flow（东方财富 push2 接口）被代理拦截
       （ConnectionError: RemoteDisconnected），无法直连。
    🔍 联网检索结论：
       - 东方财富 push2 行情接口在本机被代理阻断，非代码问题；
       - 同花顺/腾讯的个股资金流未由 AKShare 稳定封装，且同样可能受代理影响；
       - 可行的替代方案：改用「北向/板块资金流」(stock_hsgt_fund_flow_summary_em，已验证可用)
         或后续在可直连环境启用 stock_individual_fund_flow。
    按用户要求，此处「API 调用位置先留空」，返回明确不可用说明，不抛出错误。
    """
    # TODO(API留空): 待可直连环境启用：
    #   mkt = market or ("sh" if code.startswith(("60","68","9")) else "sz")
    #   df = ak.stock_individual_fund_flow(stock=code, market=mkt)
    return {
        "code": code,
        "available": False,
        "error": "个股资金流向接口（东方财富）当前网络不可用（被代理拦截）。",
        "suggestion": "可改用板块/北向资金流，或在可直连环境启用 stock_individual_fund_flow。",
        "source": "AKShare（东方财富，暂不可用）",
    }


# ---------------------------------------------------------------------------
# 7. 估值与财务指标
# ---------------------------------------------------------------------------
def get_indicators(code: str, start_year: str = "2023") -> dict:
    """获取目标股票的估值与财务指标（每股收益、每股净资产、每股现金流等）。"""
    try:
        df = _with_timeout(ak.stock_financial_analysis_indicator, symbol=code, start_year=start_year)
        if isinstance(df, dict) and "error" in df:
            return df
        return {"code": code, "start_year": start_year, "count": len(df),
                "columns": list(df.columns)[:30],
                "data": _df_to_records(df, limit=20),
                "source": "AKShare（财务分析指标）"}
    except Exception as e:
        return {"code": code, "error": f"未获取到财务指标：{e}"}


# ---------------------------------------------------------------------------
# 8. 主要财务指标摘要
# ---------------------------------------------------------------------------
def get_key_metrics(code: str, indicator: str = "按报告期") -> dict:
    """获取目标股票的主要财务指标摘要（营收、净利润、增长率、每股收益等）。"""
    try:
        df = _with_timeout(ak.stock_financial_abstract_ths, symbol=code, indicator=indicator)
        if isinstance(df, dict) and "error" in df:
            return df
        return {"code": code, "indicator": indicator, "count": len(df),
                "columns": list(df.columns)[:30],
                "data": _df_to_records(df, limit=20),
                "source": "AKShare（同花顺财务摘要）"}
    except Exception as e:
        return {"code": code, "error": f"未获取到财务摘要：{e}"}


# ---------------------------------------------------------------------------
# 9. 业绩报告 / 预告
# ---------------------------------------------------------------------------
def get_forecast(code: str, date: str = None) -> dict:
    """获取目标股票的业绩报告（按报告期，如 20240331）。不传 date 默认取最近一期。"""
    import datetime as _dt
    if not date:
        # 取上一报告期（3/6/9/12 月末）
        now = _dt.date.today()
        for m in (3, 6, 9, 12):
            if now.month > m:
                date = f"{now.year}{m:02d}31"
                break
        else:
            date = f"{now.year-1}1231"
    try:
        df = _with_timeout(ak.stock_yjbb_em, date=date)
        if isinstance(df, dict) and "error" in df:
            return df
        if df is None or len(df) == 0:
            return {"code": code, "date": date, "error": "未获取到业绩报告：返回为空"}
        hit = df[df["股票代码"].astype(str) == str(code)]
        if len(hit) == 0:
            hit = df[df["股票代码"].astype(str).str.endswith(str(code))]
        return {"code": code, "date": date, "count": len(hit),
                "data": _df_to_records(hit, limit=10),
                "source": "AKShare（东方财富业绩报表）"}
    except Exception as e:
        return {"code": code, "error": f"未获取到业绩报告：{e}"}


# ---------------------------------------------------------------------------
# 10. 技术指标全景（v7 新增；与 7. get_indicators 财务估值指标区分）
# ---------------------------------------------------------------------------
def get_technical_indicators(code: str) -> dict:
    """获取目标股票的常用技术指标（MA/MACD/RSI/KDJ/BOLL/ATR）与当前多空状态。当用户问及技术指标、MACD、RSI、KDJ、金叉死叉、趋势强弱、买卖点时调用。"""
    try:
        import data_layer
        from features import technical_snapshot
        data_layer.initialize_database()
        frame = data_layer.load_history(code, years=3)
        if frame is None or len(frame) < 60:
            return {"code": code, "error": "历史数据不足（< 60 个交易日）"}
        result = {"code": code, "source": "v7 技术面引擎（qfq 前复权日线）"}
        result.update(technical_snapshot(frame))
        return result
    except Exception as e:
        return {"code": code, "error": f"未获取到技术指标：{e}"}


# ---------------------------------------------------------------------------
# 11. 价格预测（v7 新增：统计模型 SARIMA/EMA + 波动率置信带）
# ---------------------------------------------------------------------------
def get_price_prediction(code: str, horizon: int = 10) -> dict:
    """获取目标股票未来 5/10/20 个交易日的价格预测：方向概率、支撑位、压力位、置信区间。当用户问及预测、走势、目标价、未来涨跌、上涨概率时调用。"""
    try:
        import models
        valid = [5, 10, 20]
        horizons = [h for h in valid if h >= (horizon or 10)] or [10]
        return models.price_forecast(code, horizons=horizons)
    except Exception as e:
        return {"code": code, "error": f"未获取到价格预测：{e}"}


# ---------------------------------------------------------------------------
# 12. 股票名称检索（v8 新增：本地快照 TF-IDF/拼音模糊查询，离线可用）
# ---------------------------------------------------------------------------
def search_stocks(query: str) -> dict:
    """按名称/拼音/首字母模糊检索股票，返回候选 {code, name, score} 列表。当用户用股票名称而非 6 位代码提问时调用。"""
    import stock_search
    q = (query or "").strip()
    if q.isdigit() and len(q) == 6:
        name = stock_search.get_name(q)
        if name:
            return {"query": q, "total": 1,
                    "results": [{"code": q, "name": name, "score": 1.0}],
                    "tip": ""}
    return stock_search.search_stocks(q)


# ---------------------------------------------------------------------------
# 工具注册表：函数 + functionDeclaration schema
# ---------------------------------------------------------------------------
TOOL_FUNCTIONS = {
    "search_stocks": search_stocks,
    "get_profile": get_profile,
    "get_history": get_history,
    "get_intraday": get_intraday,
    "get_financials": get_financials,
    "get_dividend": get_dividend,
    "get_capital_flow": get_capital_flow,
    "get_indicators": get_indicators,
    "get_key_metrics": get_key_metrics,
    "get_forecast": get_forecast,
    "get_technical_indicators": get_technical_indicators,
    "get_price_prediction": get_price_prediction,
}

TOOL_DECLARATIONS = [
    {
        "name": "search_stocks",
        "description": "按股票名称/拼音/拼音首字母模糊检索 A 股股票，返回 6 位代码候选列表。当用户以股票名称（如「长安汽车」「茅台」「changan」）而非代码提问时先调用本工具确认代码，再用确认的代码调用其他工具。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "股票名称、拼音或拼音首字母，如 长安汽车 / changan / CAQC"}
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_profile",
        "description": "获取目标股票的上市板块、所属行业、主营业务、成立与上市日期等公司资料。当用户问及上市板块、主营业务、行业、公司资料时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "6 位股票代码，如 600519"}
            },
            "required": ["code"],
        },
    },
    {
        "name": "get_history",
        "description": "获取目标股票历史日 K 线行情（开盘/收盘/最高/最低/成交量），默认返回近一年数据。当用户问及历史价格、K线、某段时间行情时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "6 位股票代码"},
                "start_date": {"type": "string", "description": "可选，起始日期 YYYYMMDD，默认近一年"},
                "end_date": {"type": "string", "description": "可选，结束日期 YYYYMMDD，默认今天"},
                "limit": {"type": "integer", "description": "可选，最多返回行数（默认 200），取最近 N 条"},
            },
            "required": ["code"],
        },
    },
    {
        "name": "get_intraday",
        "description": "获取目标股票指定日期的盘中分时（分钟级）行情，可定位到具体时间。当用户问及盘中、分时、实时、某时刻价格时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "6 位股票代码"},
                "date": {"type": "string", "description": "日期 YYYY-MM-DD"},
                "time": {"type": "string", "description": "可选，具体时间 HH:MM"},
            },
            "required": ["code", "date"],
        },
    },
    {
        "name": "get_financials",
        "description": "获取目标股票的三大财务报表之一（资产负债表/利润表/现金流量表）。当用户问及财务报表、资产负债表、利润、现金流时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "6 位股票代码"},
                "report_type": {"type": "string", "description": "报表类型：资产负债表 / 利润表 / 现金流量表"},
            },
            "required": ["code"],
        },
    },
    {
        "name": "get_dividend",
        "description": "获取目标股票的历史分红送配方案（派息/送股/转增/股权登记日）。当用户问及分红、送股、派息、除权时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "6 位股票代码"}
            },
            "required": ["code"],
        },
    },
    {
        "name": "get_capital_flow",
        "description": "获取目标股票个股资金流向（主力/散户净流入）。注意：当前网络环境下该接口可能不可用。当用户问及资金流向、主力资金、净流入时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "6 位股票代码"},
                "market": {"type": "string", "description": "可选，sh 或 sz"},
            },
            "required": ["code"],
        },
    },
    {
        "name": "get_indicators",
        "description": "获取目标股票的估值与财务指标（每股收益、每股净资产、每股现金流等）。当用户问及估值、每股指标、财务分析时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "6 位股票代码"},
                "start_year": {"type": "string", "description": "可选，起始年份如 2023"},
            },
            "required": ["code"],
        },
    },
    {
        "name": "get_key_metrics",
        "description": "获取目标股票的主要财务指标摘要（营收、净利润、增长率、每股收益等）。当用户问及业绩、营收、净利、增长率时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "6 位股票代码"},
                "indicator": {"type": "string", "description": "可选，按报告期 / 按年度 / 按单季"},
            },
            "required": ["code"],
        },
    },
{
        "name": "get_forecast",
        "description": "获取目标股票的业绩报告/预告（按报告期）。当用户问及业绩预告、季报、年报、业绩报告时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "6 位股票代码"},
                "date": {"type": "string", "description": "可选，报告期 YYYYMMDD，默认最近一期"},
            },
            "required": ["code"],
        },
    },
    {
        "name": "get_technical_indicators",
        "description": "获取目标股票的常用技术指标（MA/MACD/RSI/KDJ/BOLL/ATR）与当前多空趋势状态。当用户问及技术指标、MACD、RSI、KDJ、金叉死叉、趋势强弱、支撑压力位时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "6 位股票代码"}
            },
            "required": ["code"],
        },
    },
    {
        "name": "get_price_prediction",
        "description": "获取目标股票未来 5/10/20 个交易日的价格预测：方向（偏多/中性/偏空）、上涨概率、支撑位、压力位、多周期置信区间。当用户问及预测、走势、未来涨跌、目标价、上涨概率时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "6 位股票代码"},
                "horizon": {"type": "integer", "description": "可选，关注周期（交易日）：5、10 或 20，默认 10"},
            },
            "required": ["code"],
        },
    },
]


def call_tool(name: str, args: dict) -> dict:
    """统一入口：按名称执行工具函数，返回可序列化结果。"""
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        return {"error": f"未知工具：{name}"}
    try:
        return fn(**(args or {}))
    except Exception as e:
        return {"error": f"工具 {name} 执行失败：{e}"}
