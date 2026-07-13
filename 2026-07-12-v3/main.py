from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, List, AsyncGenerator
import os, json, datetime
import session_store as store
import agent_runner as agent

app = FastAPI(title="股票信息助手")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
store.init_db()

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    reply: str
    profile: Optional[dict] = None
    history: Optional[List[dict]] = None
    intraday: Optional[List[dict]] = None
    fallback: Optional[dict] = None


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


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    res = agent.run_agent(req.message)
    store.add_message(req.session_id, "user", req.message)
    store.add_message(req.session_id, "assistant", res["reply"])
    # 首条用户消息后，将会话标题更新为摘要
    _auto_rename(req.session_id, req.message)
    return ChatResponse(**res)


def _auto_rename(sid: str, first_user_msg: str):
    """若会话仍为默认标题，则用 LLM 摘要替换。"""
    sessions = store.list_sessions()
    cur = next((s for s in sessions if s["id"] == sid), None)
    if cur and cur["title"] in ("新会话", "", None):
        title = agent.llm_client.summarize_title(first_user_msg)
        store.rename_session(sid, title)


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """SSE 流式输出：逐段返回结果，最后返回结构化数据。"""
    async def event_gen() -> AsyncGenerator[str, None]:
        yield _sse("start", "正在分析请求……")
        res = agent.run_agent(req.message)
        for chunk in res["reply"].split("\n\n"):
            if chunk.strip():
                yield _sse("chunk", chunk.strip())
        yield _sse("data", json.dumps({
            "profile": res.get("profile"),
            "history": res.get("history"),
            "intraday": res.get("intraday"),
            "fallback": res.get("fallback"),
        }, ensure_ascii=False))
        yield _sse("done", "完成")
        store.add_message(req.session_id, "user", req.message)
        store.add_message(req.session_id, "assistant", res["reply"])
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
    if fmt == "json":
        return JSONResponse({"title": title, "messages": msgs})
    lines = [f"# {title}", "", f"> 导出时间：{datetime.datetime.now().isoformat(timespec='seconds')}", ""]
    for m in msgs:
        role = "用户" if m["role"] == "user" else "助手"
        lines.append(f"## {role}（{m['created_at']}）")
        lines.append(m["content"])
        lines.append("")
    return JSONResponse({"markdown": "\n".join(lines)})


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
