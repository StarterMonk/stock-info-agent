"""
v8 股票名称检索层（RAG 检索侧，本地离线可用）：

- 快照：A 股全量名单（Sina 沪/深/北，East Money 全量兜底）→ SQLite 表 stock_info
- 索引：名称 + 拼音全拼 + 拼音首字母 的字符 bigram TF-IDF 向量 → pickle 持久化
- 检索：打分级联：精确包含（名称/全拼/首字母）→ TF-IDF 余弦 → difflib 兜底
"""
import os
import re
import pickle
import datetime
import logging
import sqlite3

import akshare as ak
from pypinyin import lazy_pinyin, Style
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

import data_layer

logger = logging.getLogger(__name__)

DB_PATH = data_layer.DB_PATH
INDEX_PATH = os.path.join(os.path.dirname(__file__), "stock_search_index.pkl")
STALE_DAYS = 7
MIN_TFIDF_SCORE = 0.06
MIN_DIFFLIB_RATIO = 0.62

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
        CREATE TABLE IF NOT EXISTS stock_info(
            stock_code      TEXT PRIMARY KEY,
            stock_name      TEXT NOT NULL,
            full_name       TEXT,
            exchange        TEXT,
            industry        TEXT,
            listing_date    TEXT,
            pinyin_full     TEXT,
            pinyin_initials TEXT,
            updated_at      TEXT NOT NULL
        )""")
    conn.commit()


def _pinyin_of(name: str) -> tuple:
    full = "".join(lazy_pinyin(name, style=Style.NORMAL)).replace(" ", "")
    initials = "".join(lazy_pinyin(name, style=Style.FIRST_LETTER)).replace(" ", "")
    return full, initials


def _fmt_date(value) -> str:
    if value is None:
        return ""
    return str(value)[:10]


def _fetch_sina() -> list:
    """Sina 沪/深/北三表 → (code, name, full_name, exchange, industry, listing_date)。"""
    rows = []
    try:
        sh = ak.stock_info_sh_name_code()
        for _, r in sh.iterrows():
            rows.append((str(r["证券代码"]).zfill(6), str(r["证券简称"]).strip(),
                         str(r.get("证券全称") or "").strip(), "sh", "", _fmt_date(r.get("上市日期"))))
    except Exception as exc:
        logger.warning("Sina 沪表失败：%s", exc)

    try:
        sz = ak.stock_info_sz_name_code()
        for _, r in sz.iterrows():
            rows.append((str(r["A股代码"]).zfill(6), str(r["A股简称"]).strip(), "",
                         "sz", str(r.get("所属行业") or "").strip(), _fmt_date(r.get("A股上市日期"))))
    except Exception as exc:
        logger.warning("Sina 深表失败：%s", exc)

    try:
        bj = ak.stock_info_bj_name_code()
        for _, r in bj.iterrows():
            rows.append((str(r["证券代码"]).zfill(6), str(r["证券简称"]).strip(), "",
                         "bj", str(r.get("所属行业") or "").strip(), _fmt_date(r.get("上市日期"))))
    except Exception as exc:
        logger.warning("Sina 北表失败：%s", exc)
    return rows


def _fetch_em() -> list:
    """East Money 全量兜底（慢，仅当 Sina 为空时使用）。"""
    df = ak.stock_info_a_code_name()
    rows = []
    for _, r in df.iterrows():
        code = str(r["code"]).zfill(6)
        exchange = "sh" if code.startswith("6") else ("bj" if code.startswith(("4", "8", "92")) else "sz")
        rows.append((code, str(r["name"]).strip(), "", exchange, "", ""))
    return rows


def _corpus_rows():
    conn = _get_connection()
    return conn.execute(
        "SELECT stock_code, stock_name, pinyin_full, pinyin_initials FROM stock_info").fetchall()


def _build_with_names() -> int:
    """语料 = 名称 + 全拼 + 首字母，字符 bigram TF-IDF；索引写入 names 映射。"""
    rows = _corpus_rows()
    docs, codes, names = [], [], {}
    for code, name, pinyin_full, initials in rows:
        docs.append(f"{name} {pinyin_full} {initials}")
        codes.append(code)
        names[code] = name
    if not docs:
        return 0
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 3), min_df=1, sublinear_tf=True)
    matrix = vectorizer.fit_transform(docs)
    with open(INDEX_PATH, "wb") as handle:
        pickle.dump({"vectorizer": vectorizer, "matrix": matrix, "codes": codes, "names": names,
                     "built_at": datetime.datetime.now().isoformat(timespec="seconds")}, handle)
    logger.info("stock_info 向量索引重建完成：%d 只", len(codes))
    return len(codes)


def build_index() -> int:
    return _build_with_names()


def sync_snapshot(force: bool = False) -> dict:
    """拉取全量 A 股名单写入 stock_info（含拼音），并重建向量索引。"""
    initialize_database()
    rows, source = [], ""
    try:
        rows = _fetch_sina()
        source = "sina"
    except Exception as exc:
        logger.warning("Sina 名单拉取失败：%s", exc)
    if not rows:
        try:
            rows = _fetch_em()
            source = "em"
        except Exception as exc2:
            logger.error("East Money 兜底也失败：%s", exc2)
            return {"ok": False, "error": str(exc2)}

    merged = {}
    for code, name, full_name, exchange, industry, listing_date in rows:
        if not code or not name:
            continue
        prev = merged.get(code)
        if prev is None:
            merged[code] = {"code": code, "name": name, "full_name": full_name,
                            "exchange": exchange, "industry": industry,
                            "listing_date": listing_date}
        else:
            if not prev["full_name"] and full_name:
                prev["full_name"] = full_name
            if exchange and not prev["exchange"]:
                prev["exchange"] = exchange
            if not prev["industry"] and industry:
                prev["industry"] = industry

    conn = _get_connection()
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    batch = []
    for item in merged.values():
        pinyin_full, pinyin_initials = (_pinyin_of(item["name"]) if item["name"] else ("", ""))
        batch.append((item["code"], item["name"], item["full_name"], item["exchange"],
                      item["industry"], item["listing_date"],
                      pinyin_full, pinyin_initials, stamp))
    conn.executemany("""
        INSERT OR REPLACE INTO stock_info(
            stock_code, stock_name, full_name, exchange, industry,
            listing_date, pinyin_full, pinyin_initials, updated_at)
        VALUES(?,?,?,?,?,?,?,?,?)""", batch)
    conn.commit()

    count = build_index()
    return {"ok": True, "source": source, "total": len(merged), "indexed": count,
            "updated_at": stamp}


def _load_index():
    if not os.path.exists(INDEX_PATH):
        return None
    try:
        with open(INDEX_PATH, "rb") as handle:
            return pickle.load(handle)
    except Exception as exc:
        logger.warning("索引文件损坏，将重建：%s", exc)
        return None


def is_stale() -> bool:
    index = _load_index()
    if index is None:
        return True
    try:
        built = datetime.datetime.fromisoformat(index["built_at"])
        return (datetime.datetime.now() - built).days >= STALE_DAYS
    except Exception:
        return True


def ensure_ready(force: bool = False):
    """启动/查询前确保数据齐备；缺失或过期则同步重建（网络依赖，失败静默降级）。"""
    initialize_database()
    conn = _get_connection()
    count = conn.execute("SELECT COUNT(*) FROM stock_info").fetchone()[0]
    if (force or is_stale()) and count < 100:
        try:
            sync_snapshot(force=force)
        except Exception as exc:
            logger.warning("stock_info 快照刷新失败（可稍后重试）：%s", exc)
    elif force:
        try:
            sync_snapshot(force=True)
        except Exception as exc:
            logger.warning("强制刷新失败：%s", exc)


def _norm_pinyin(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def lookup(text: str, top_k: int = 5) -> list:
    """打分级联检索：名称/全拼/首字母包含 > TF-IDF 余弦 > difflib。"""
    query = (text or "").strip()
    if not query:
        return []
    results = {}  # code -> (score, name)

    def add(code, name, score):
        if code in results and results[code][0] >= score:
            return
        results[code] = (score, name)

    # ---- 1. 精确包含：名称 / 拼音全拼 / 拼音首字母 ----
    rows = _corpus_rows()
    q_py = _norm_pinyin(query)
    for code, name, pinyin_full, initials in rows:
        if name and name in query:
            add(code, name, 1.0)
        if pinyin_full and q_py and pinyin_full in q_py:
            add(code, name, 0.98)
        if initials and q_py and initials.lower() in q_py:
            add(code, name, 0.96)

    # ---- 2. TF-IDF 余弦（错字 / 部分名 / 变形）----
    best_contains = max([s for s, _ in results.values()] or [0.0])
    if best_contains < 1.0:
        index = _load_index()
        if index:
            names_map = index.get("names", {})
            vector = index["vectorizer"].transform([query])
            scores = cosine_similarity(index["matrix"], vector).ravel()
            for i, score in enumerate(scores):
                if score >= MIN_TFIDF_SCORE:
                    code = index["codes"][i]
                    add(code, names_map.get(code, code), round(float(score), 3))

    # ---- 3. difflib 兜底 ----
    if not results:
        try:
            from difflib import get_close_matches
            names_map = {r[1]: r[0] for r in rows}
            for match_name in get_close_matches(query, list(names_map), n=5, cutoff=MIN_DIFFLIB_RATIO):
                add(names_map[match_name], match_name, 0.9)
        except Exception:
            pass

    ranked = sorted(results.items(), key=lambda kv: (-kv[1][0], kv[0]))
    items = [{"code": c, "name": n, "score": s} for c, (s, n) in ranked[:top_k]]
    return items


def resolve(text: str):
    """实体解析：唯一且高置信 → code；模糊/多候选 → None（交由 LLM 或追问）。"""
    items = lookup(text, top_k=3)
    if not items:
        return None
    top = items[0]
    if top["score"] >= 0.96:
        strong = [i for i in items if i["score"] >= 0.96]
        return top["code"] if len(strong) == 1 else None
    if top["score"] >= 0.30 and (len(items) < 2 or top["score"] - items[1]["score"] >= 0.10):
        return top["code"]
    return None


def search_stocks(query: str) -> dict:
    """工具 search_stocks 返回体：top 候选列表。"""
    items = lookup(query or "", top_k=5)
    return {"query": query or "", "total": len(items),
            "results": items[:5],
            "tip": "请选择其中一个 code 继续查询/分析。" if items else "未找到匹配的股票，请换关键词。"}


def get_name(code: str) -> str:
    conn = _get_connection()
    row = conn.execute("SELECT stock_name FROM stock_info WHERE stock_code=?", (code,)).fetchone()
    return row[0] if row else ""