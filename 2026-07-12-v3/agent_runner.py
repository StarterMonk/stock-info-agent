import re, datetime
import akshare as ak
import llm_client

_name_map = None


def _build_name_map():
    global _name_map
    if _name_map is None:
        try:
            df = ak.stock_info_a_code_name()
            _name_map = dict(zip(df["名称"], df["代码"]))
        except Exception:
            _name_map = {}
    return _name_map


# 本地常用股票名称->代码映射（AKShare 名称接口被代理拦截时的兜底）
_LOCAL_NAME_MAP = {
    "贵州茅台": "600519", "茅台": "600519",
    "宁德时代": "300750", "比亚迪": "002594",
    "中国平安": "601318", "招商银行": "600036",
    "五粮液": "000858", "隆基绿能": "601012",
    "东方财富": "300059", "中信证券": "600030",
    "工商银行": "601398", "贵州茅台酒": "600519",
}


def _resolve_code(text):
    m = re.search(r"\b(\d{6})\b", text)
    if m:
        return m.group(1)
    # 先查本地映射
    for name, code in _LOCAL_NAME_MAP.items():
        if name in text:
            return code
    # 再查 AKShare 名称映射（可能为空）
    for name, code in _build_name_map().items():
        if name in text:
            return code
    return None


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


def get_profile(code):
    try:
        df = ak.stock_profile_cninfo(symbol=code)
        if df is None or len(df) == 0:
            return {"code": code, "error": "未获取到上市详情：返回为空"}
        r = df.iloc[0]
        return {"code": code,
                "name": str(r.get("A股简称", r.get("公司名称", code))),
                "full_name": str(r.get("公司名称", "")),
                "board": _board_from_code(code),
                "market": str(r.get("所属市场", "")),
                "industry": str(r.get("所属行业", "未获取到")),
                "main_business": str(r.get("主营业务", "未获取到")),
                "found_date": str(r.get("成立日期", "未获取到")),
                "list_date": str(r.get("上市日期", "未获取到")),
                "source": "AKShare（巨潮资讯网 cninfo）"}
    except Exception as e:
        return {"code": code, "error": f"未获取到上市详情：{e}"}


def _sina_symbol(code):
    if code.startswith(("60", "68", "9", "5", "11", "113", "110")):
        return "sh" + code
    return "sz" + code


def get_history(code, start, end):
    try:
        sym = _sina_symbol(code)
        df = ak.stock_zh_a_daily(symbol=sym, start_date=start, end_date=end)
        df = df.copy()
        df["date"] = df["date"].astype(str).str.replace("-", "", regex=False)
        df = df[(df["date"] >= start) & (df["date"] <= end)]
        return [{"date": str(r["date"]), "open": float(r["open"]),
                 "close": float(r["close"]), "high": float(r["high"]),
                 "low": float(r["low"]), "volume": float(r["volume"])}
                for _, r in df.iterrows()]
    except Exception as e:
        return {"error": f"未获取到历史行情：{e}"}


def get_intraday(code, date_str, time_str=None):
    """获取指定日期的分时（分钟级）行情；time_str 形如 '14:00' 可定位到具体分钟。"""
    try:
        sym = _sina_symbol(code)
        df = ak.stock_zh_a_minute(symbol=sym, period="1", adjust="")
        df = df.copy()
        df["day"] = df["day"].astype(str)
        day_rows = df[df["day"].str.startswith(date_str)].copy()
        if time_str:
            hhmm = time_str.replace(":", "")  # "1400"
            # 从 "2026-07-10 14:00:00" 提取小时分钟 "1400"
            day_rows["hhmm"] = day_rows["day"].str.extract(r"(\d{2}):(\d{2}):\d{2}$").agg("".join, axis=1)
            match = day_rows[day_rows["hhmm"] == hhmm]
            if len(match) == 0:
                # 取该日最后一根作为近似
                match = day_rows.tail(1)
            rows = match
        else:
            rows = day_rows
        return [{"time": str(r["day"]), "open": float(r["open"]),
                 "close": float(r["close"]), "high": float(r["high"]),
                 "low": float(r["low"]), "volume": float(r["volume"])}
                for _, r in rows.iterrows()]
    except Exception as e:
        return {"error": f"未获取到盘中行情：{e}"}


def web_fallback(code, message):
    """方式二：当 AKShare 不可用时，检索公开财经网站补充信息。"""
    import requests
    from bs4 import BeautifulSoup
    name = None
    # 先尝试从 AKShare 名称映射拿到股票名（若可用）
    try:
        name = _build_name_map().get(code)
    except Exception:
        name = None
    results = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    # 新浪财经个股页
    try:
        sina_url = f"https://finance.sina.com.cn/realstock/company/{_sina_symbol(code)}/nc.shtml"
        r = requests.get(sina_url, headers=headers, timeout=10)
        if r.status_code == 200:
            r.encoding = r.apparent_encoding or "utf-8"
            soup = BeautifulSoup(r.text, "html.parser")
            title = soup.find("title")
            if title:
                results.append(f"新浪财经：{title.get_text(strip=True)}（{sina_url}）")
    except Exception as e:
        results.append(f"新浪财经检索失败：{e}")
    # 东方财富个股页
    try:
        em_url = f"https://quote.eastmoney.com/{_sina_symbol(code)}.html"
        r = requests.get(em_url, headers=headers, timeout=10)
        if r.status_code == 200:
            r.encoding = r.apparent_encoding or "utf-8"
            soup = BeautifulSoup(r.text, "html.parser")
            title = soup.find("title")
            if title:
                results.append(f"东方财富：{title.get_text(strip=True)}（{em_url}）")
    except Exception as e:
        results.append(f"东方财富检索失败：{e}")
    if not results:
        return {"note": "网站兜底未获取到有效信息", "links": []}
    return {"note": "以下为公开财经网站检索结果（方式二兜底）", "links": results,
            "source": "新浪财经 / 东方财富"}


def _parse_dates(text):
    m = re.findall(r"(\d{4})-(\d{2})-(\d{2})", text)
    if len(m) >= 2:
        s = "".join(m[0]); e = "".join(m[1])
    elif len(m) == 1:
        s = "".join(m[0]); e = datetime.date.today().strftime("%Y%m%d")
    else:
        end = datetime.date.today(); start = end - datetime.timedelta(days=30)
        s, e = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
    return s, e


def run_agent(message):
    intent = llm_client.parse_intent(message)
    code = (intent.get("code")
            or _resolve_code(message)
            or _resolve_code(intent.get("name", ""))
            or _LOCAL_NAME_MAP.get(intent.get("name", "")))
    if not code:
        return {"reply": "未能识别股票代码或名称，请补充（如「600519」或「贵州茅台」）。"}
    intents = intent.get("intent", [])
    reply, profile, history, intraday, fallback = [], None, None, None, None
    if "profile" in intents:
        p = get_profile(code); profile = p if "error" not in p else None
        if profile:
            reply.append(f"**{p.get('name', code)}（{code}）上市详情**\n"
                         f"- 上市板块：{p.get('board', '未获取到')}\n"
                         f"- 所属市场：{p.get('market', '未获取到')}\n"
                         f"- 所属行业：{p.get('industry', '未获取到')}\n"
                         f"- 主营业务：{p.get('main_business', '未获取到')}\n"
                         f"- 成立日期：{p.get('found_date', '未获取到')}\n"
                         f"- 上市日期：{p.get('list_date', '未获取到')}\n"
                         f"- 来源：{p.get('source', '')}")
        else:
            reply.append(f"**{code} 上市详情**：AKShare 未获取到，启用网站兜底检索……")
            fallback = web_fallback(code, message)
    if "history" in intents:
        s = intent.get("start_date") or intent.get("date") or _parse_dates(message)[0]
        e = intent.get("end_date") or intent.get("date") or _parse_dates(message)[1]
        s, e = s.replace("-", ""), e.replace("-", "")
        h = get_history(code, s, e); history = h if isinstance(h, list) else None
        cnt = len(h) if isinstance(h, list) else 0
        if history:
            reply.append(f"**历史行情（{s}~{e}，共 {cnt} 条）**\n来源：AKShare（新浪财经日线）")
        else:
            reply.append(f"**历史行情（{s}~{e}）**：AKShare 未获取到，启用网站兜底检索……")
            if fallback is None:
                fallback = web_fallback(code, message)
    if "intraday" in intents:
        d = intent.get("date") or datetime.date.today().strftime("%Y-%m-%d")
        t = intent.get("time")
        intra = get_intraday(code, d, t)
        intraday = intra if isinstance(intra, list) else None
        if intraday:
            label = f"{d} {t + ' 附近' if t else '全天'}"
            lines = [f"**盘中行情（{label}，共 {len(intraday)} 条）**\n来源：AKShare（新浪财经分钟线）"]
            for r in intraday[:10]:
                lines.append(f"- {r['time']} 开:{r['open']} 收:{r['close']} 高:{r['high']} 低:{r['low']} 量:{r['volume']}")
            if len(intraday) > 10:
                lines.append(f"- …（共 {len(intraday)} 条，已省略）")
            reply.append("\n".join(lines))
        else:
            reply.append(f"**盘中行情（{d} {t or ''}）**：AKShare 未获取到，启用网站兜底检索……")
            if fallback is None:
                fallback = web_fallback(code, message)
    if fallback:
        reply.append(f"**网站兜底（方式二）**\n{fallback.get('note', '')}\n"
                     + "\n".join(f"- {l}" for l in fallback.get("links", [])))
    return {"reply": "\n\n".join(reply), "profile": profile, "history": history,
            "intraday": intraday, "fallback": fallback}
