import sqlite3, os, uuid, datetime

DB = os.path.join(os.path.dirname(__file__), "sessions.db")


def _conn():
    return sqlite3.connect(DB)


def init_db():
    c = _conn(); cur = c.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS sessions(
        id TEXT PRIMARY KEY, title TEXT, created_at TEXT, updated_at TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS messages(
        id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT,
        role TEXT, content TEXT, created_at TEXT)""")
    c.commit(); c.close()


def create_session(title="新会话"):
    sid = uuid.uuid4().hex
    now = datetime.datetime.now().isoformat(timespec="seconds")
    c = _conn(); cur = c.cursor()
    cur.execute("INSERT INTO sessions VALUES(?,?,?,?)", (sid, title, now, now))
    c.commit(); c.close()
    return {"id": sid, "title": title, "created_at": now, "updated_at": now}


def list_sessions():
    c = _conn(); cur = c.cursor()
    cur.execute("SELECT id,title,created_at,updated_at FROM sessions ORDER BY updated_at DESC")
    rows = [dict(zip(["id", "title", "created_at", "updated_at"], r)) for r in cur.fetchall()]
    c.close(); return rows


def get_messages(sid):
    c = _conn(); cur = c.cursor()
    cur.execute("SELECT role,content,created_at FROM messages WHERE session_id=? ORDER BY id", (sid,))
    return [dict(zip(["role", "content", "created_at"], r)) for r in cur.fetchall()]


def add_message(sid, role, content):
    now = datetime.datetime.now().isoformat(timespec="seconds")
    c = _conn(); cur = c.cursor()
    cur.execute("INSERT INTO messages(session_id,role,content,created_at) VALUES(?,?,?,?)",
                (sid, role, content, now))
    cur.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, sid))
    c.commit(); c.close()


def rename_session(sid, title):
    now = datetime.datetime.now().isoformat(timespec="seconds")
    c = _conn(); cur = c.cursor()
    cur.execute("UPDATE sessions SET title=?,updated_at=? WHERE id=?", (title, now, sid))
    c.commit(); c.close()


def delete_session(sid):
    c = _conn(); cur = c.cursor()
    cur.execute("DELETE FROM messages WHERE session_id=?", (sid,))
    cur.execute("DELETE FROM sessions WHERE id=?", (sid,))
    c.commit(); c.close()
