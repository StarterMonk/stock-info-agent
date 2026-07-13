"""
v4 长期记忆层（Long-term Memory）。

设计：
- 每个会话（session）维护一份「长期记忆」文本，持久化在 SQLite 的 long_memory 表。
- 每次用户提问后，把「用户问题 + 本轮工具结果摘要」交给 LLM 抽取增量事实，
  追加/合并进长期记忆。下一轮对话开始时注入到 system 指令，使 Agent 具备跨轮记忆。
- 短期记忆（short-term）由 main.py 从 messages 表读取最近 N 条，作为 contents 传入 LLM。

表结构：
  long_memory(session_id TEXT PRIMARY KEY, memory TEXT, updated_at TEXT)
"""
import os
import sqlite3
import datetime

DB_PATH = os.environ.get("V4_DB_PATH", os.path.join(os.path.dirname(__file__), "v4_sessions.db"))


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS long_memory (
            session_id TEXT PRIMARY KEY,
            memory TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        )"""
    )
    return conn


def get_long_memory(session_id: str) -> str:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT memory FROM long_memory WHERE session_id=?", (session_id,)
        ).fetchone()
        return row[0] if row else ""
    finally:
        conn.close()


def set_long_memory(session_id: str, memory: str):
    conn = _conn()
    try:
        now = datetime.datetime.now().isoformat(timespec="seconds")
        conn.execute(
            "INSERT INTO long_memory(session_id, memory, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(session_id) DO UPDATE SET memory=excluded.memory, updated_at=excluded.updated_at",
            (session_id, memory, now),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 长期记忆抽取（依赖 llm_client）
# ---------------------------------------------------------------------------
_MEMORY_EXTRACT_PROMPT = """你是一个对话长期记忆抽取器。下面给出「当前长期记忆」与「本轮新增信息」。
请合并二者，产出一份简洁、去重、按要点组织的长期记忆文本（中文，每条一行，不超过 200 字）。
只保留对后续对话有用的稳定事实：用户关注的股票、已查询过的信息、用户偏好等。不要输出解释。
若当前长期记忆为空，则直接基于新增信息生成。只返回记忆文本。"""


def update_long_memory(session_id: str, new_facts: str):
    """把本轮新增事实合并进长期记忆并持久化。new_facts 为空则跳过。"""
    if not new_facts or not new_facts.strip():
        return get_long_memory(session_id)
    import llm_client
    current = get_long_memory(session_id)
    if not llm_client.GEMINI_API_KEY:
        # 无 LLM 时直接追加（简单去重）
        merged = current + ("\n" if current and not current.endswith("\n") else "") + new_facts.strip()
        set_long_memory(session_id, merged)
        return merged
    try:
        prompt = f"【当前长期记忆】\n{current or '(空)'}\n\n【本轮新增信息】\n{new_facts.strip()}"
        text = llm_client._call_gemini(prompt, system_prompt=_MEMORY_EXTRACT_PROMPT, temperature=0.2)
        merged = text.strip()
        set_long_memory(session_id, merged)
        return merged
    except Exception as e:
        print(f"[memory] 抽取失败，直接追加：{e}")
        merged = current + ("\n" if current and not current.endswith("\n") else "") + new_facts.strip()
        set_long_memory(session_id, merged)
        return merged
