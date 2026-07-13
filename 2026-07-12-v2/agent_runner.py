import re, datetime
import akshare as ak

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


def _resolve_code(text):
    m = re.search(r"\b(\d{6})\b", text)
    if m:
        return m.group(1)
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
    m = re.findall(r"(\d{4})[-/]?(\d{2})[-/]?(\d{2})", text)
    if len(m) >= 2:
        s = "".join(m[0]); e = "".join(m[1])
    elif len(m) == 1:
        s = "".join(m[0]); e = datetime.date.today().strftime("%Y%m%d")
    else:
        end = datetime.date.today(); start = end - datetime.timedelta(days=30)
        s, e = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
    return s, e


def run_agent(message):
    code = _resolve_code(message)
    if not code:
        return {"reply": "未能识别股票代码或名称，请补充（如「600519」或「贵州茅台」）。"}
    want_p = any(k in message for k in ["上市", "板块", "主营", "行业", "上市日期", "资料"])
    want_h = any(k in message for k in ["行情", "价格", "开盘", "收盘", "最高", "最低", "历史", "K线", "成交量"])
    if not want_p and not want_h:
        want_p = want_h = True
    reply, profile, history, fallback = [], None, None, None
    if want_p:
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
    if want_h:
        s, e = _parse_dates(message)
        h = get_history(code, s, e); history = h if isinstance(h, list) else None
        cnt = len(h) if isinstance(h, list) else 0
        if history:
            reply.append(f"**历史行情（{s}~{e}，共 {cnt} 条）**\n来源：AKShare（新浪财经日线）")
        else:
            reply.append(f"**历史行情（{s}~{e}）**：AKShare 未获取到，启用网站兜底检索……")
            if fallback is None:
                fallback = web_fallback(code, message)
    if fallback:
        reply.append(f"**网站兜底（方式二）**\n{fallback.get('note', '')}\n"
                     + "\n".join(f"- {l}" for l in fallback.get("links", [])))
    return {"reply": "\n\n".join(reply), "profile": profile, "history": history,
            "fallback": fallback}
