from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, List, AsyncGenerator
import os, json, datetime
import session_store as store
import agent_runner as agent
import memory_store as mem
import llm_client

app = FastAPI(title="股票信息助手 v4")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
store.init_db()

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
SHORT_TERM_LIMIT = 12  # 短期记忆：最近 N 轮（user+assistant 成对）


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    reply: str
    tool_calls: Optional[List[dict]] = None
    chart: Optional[dict] = None


@app.get("/api/sessions")
def list_sessions():
    return store.list_sessions()


@app.post("/api/sessions")
def create_session():
    return store.create_session()


@app.get("/api/sessions/{sid}/messages")
def get_messages(sid: str):
    return store.get_messages(sid)


class RenameRequest(BaseModel):
    title: str


@app.put("/api/sessions/{sid}")
def rename(sid: str, req: RenameRequest):
    store.rename_session(sid, req.title)
    return {"ok": True}


@app.delete("/api/sessions/{sid}")
def delete(sid: str):
    store.delete_session(sid)
    return {"ok": True}


def _build_short_history(sid: str):
    """从 messages 表读取最近 N 轮，构造 Gemini contents 所需的 [{role, parts}]。"""
    msgs = store.get_messages(sid)
    recent = msgs[-SHORT_TERM_LIMIT * 2:]
    history = []
    for m in recent:
        role = "user" if m["role"] == "user" else "model"
        history.append({"role": role, "parts": [{"text": m["content"]}]})
    return history


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    long_memory = mem.get_long_memory(req.session_id)
    history = _build_short_history(req.session_id)
    res = agent.run_agent(req.message, history=history, long_memory=long_memory)
    store.add_message(req.session_id, "user", req.message)
    store.add_message(req.session_id, "assistant", res["reply"])
    if res.get("long_memory_facts"):
        mem.update_long_memory(req.session_id, res["long_memory_facts"])
    _auto_rename(req.session_id, req.message)
    return ChatResponse(reply=res["reply"], tool_calls=res.get("tool_calls"),
                        chart=res.get("chart"))


def _auto_rename(sid: str, first_user_msg: str):
    sessions = store.list_sessions()
    cur = next((s for s in sessions if s["id"] == sid), None)
    if cur and cur["title"] in ("新会话", "", None):
        title = llm_client.summarize_title(first_user_msg)
        store.rename_session(sid, title)


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    async def event_gen() -> AsyncGenerator[str, None]:
        yield _sse("start", "正在分析请求……")
        long_memory = mem.get_long_memory(req.session_id)
        history = _build_short_history(req.session_id)
        res = agent.run_agent(req.message, history=history, long_memory=long_memory)
        for tc in res.get("tool_calls", []):
            yield _sse("tool", json.dumps(tc, ensure_ascii=False))
        for chunk in res["reply"].split("\n"):
            if chunk.strip():
                yield _sse("chunk", chunk.strip())
        yield _sse("data", json.dumps({
            "tool_calls": res.get("tool_calls"),
            "chart": res.get("chart"),
        }, ensure_ascii=False))
        yield _sse("done", "完成")
        store.add_message(req.session_id, "user", req.message)
        store.add_message(req.session_id, "assistant", res["reply"])
        if res.get("long_memory_facts"):
            mem.update_long_memory(req.session_id, res["long_memory_facts"])
        _auto_rename(req.session_id, req.message)
    return StreamingResponse(event_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


@app.get("/api/sessions/{sid}/export")
def export_session(sid: str, fmt: str = "markdown"):
    msgs = store.get_messages(sid)
    sessions = store.list_sessions()
    title = next((s["title"] for s in sessions if s["id"] == sid), "会话")
    long_memory = mem.get_long_memory(sid)
    if fmt == "json":
        return JSONResponse({"title": title, "messages": msgs, "long_memory": long_memory})
    lines = [f"# {title}", "", f"> 导出时间：{datetime.datetime.now().isoformat(timespec='seconds')}", ""]
    if long_memory:
        lines.append("## 长期记忆")
        lines.append(long_memory)
        lines.append("")
    for m in msgs:
        role = "用户" if m["role"] == "user" else "助手"
        lines.append(f"## {role}（{m['created_at']}）")
        lines.append(m["content"])
        lines.append("")
    return JSONResponse({"markdown": "\n".join(lines)})


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
