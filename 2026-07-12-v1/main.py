from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import os
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
    return ChatResponse(**res)


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
