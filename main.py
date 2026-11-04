import os, time, sqlite3
import jwt
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, Header
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from google.oauth2 import id_token
from google.auth.transport import requests as greq
import rag

CLIENT_ID = os.environ["GOOGLE_CLIENT_ID"]
SECRET = os.environ["JWT_SECRET"]
os.makedirs("data", exist_ok=True)
db = sqlite3.connect("data/app.db", check_same_thread=False)
db.row_factory = sqlite3.Row
db.executescript("""
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, sub TEXT UNIQUE, email TEXT,
  name TEXT, college TEXT, class_name TEXT, dob TEXT);
CREATE TABLE IF NOT EXISTS docs(id INTEGER PRIMARY KEY, user_id INT, filename TEXT,
  chunks INT, created REAL);""")
app = FastAPI()

def make_token(payload, ttl):
    return jwt.encode({**payload, "exp": time.time() + ttl}, SECRET, "HS256")

def current_user(authorization: str = Header(None)):
    try:
        data = jwt.decode((authorization or "").replace("Bearer ", ""), SECRET, ["HS256"])
        u = db.execute("SELECT * FROM users WHERE id=?", (data["uid"],)).fetchone()
        assert u
        return u
    except Exception:
        raise HTTPException(401, "Not logged in")

class GoogleIn(BaseModel): credential: str
class RegisterIn(BaseModel):
    signup_token: str; name: str; college: str; class_name: str; dob: str
class AskIn(BaseModel): question: str

@app.get("/api/config")
def config(): return {"client_id": CLIENT_ID}

@app.post("/api/auth/google")
def google_auth(body: GoogleIn):
    try:
        info = id_token.verify_oauth2_token(body.credential, greq.Request(), CLIENT_ID)
    except Exception:
        raise HTTPException(401, "Invalid Google sign-in")
    u = db.execute("SELECT * FROM users WHERE sub=?", (info["sub"],)).fetchone()
    if u:
        return {"registered": True, "token": make_token({"uid": u["id"]}, 7 * 86400),
                "user": dict(u)}
    st = make_token({"sub": info["sub"], "email": info["email"]}, 900)
    return {"registered": False, "signup_token": st, "name": info.get("name", "")}

@app.post("/api/auth/register")
def register(b: RegisterIn):
    try:
        d = jwt.decode(b.signup_token, SECRET, ["HS256"])
    except Exception:
        raise HTTPException(401, "Sign-up expired, please sign in again")
    cur = db.execute("INSERT OR IGNORE INTO users(sub,email,name,college,class_name,dob) "
                     "VALUES(?,?,?,?,?,?)",
                     (d["sub"], d["email"], b.name, b.college, b.class_name, b.dob))
    db.commit()
    u = db.execute("SELECT * FROM users WHERE sub=?", (d["sub"],)).fetchone()
    return {"token": make_token({"uid": u["id"]}, 7 * 86400), "user": dict(u)}

@app.get("/api/me")
def me(u=Depends(current_user)): return dict(u)

@app.get("/api/notes")
def list_notes(u=Depends(current_user)):
    return [dict(r) for r in db.execute(
        "SELECT id, filename, chunks FROM docs WHERE user_id=? ORDER BY id DESC", (u["id"],))]

@app.post("/api/notes")
async def upload(file: UploadFile = File(...), u=Depends(current_user)):
    if not file.filename.lower().endswith((".pdf", ".txt", ".md")):
        raise HTTPException(400, "Upload PDF, TXT or MD files")
    data = await file.read()
    if len(data) > 25 * 1024 * 1024: raise HTTPException(400, "File too large (25MB max)")
    cur = db.execute("INSERT INTO docs(user_id,filename,chunks,created) VALUES(?,?,0,?)",
                     (u["id"], file.filename, time.time()))
    n = rag.index_file(u["id"], cur.lastrowid, file.filename, data)
    db.execute("UPDATE docs SET chunks=? WHERE id=?", (n, cur.lastrowid)); db.commit()
    return {"id": cur.lastrowid, "filename": file.filename, "chunks": n}

@app.delete("/api/notes/{doc_id}")
def delete_note(doc_id: int, u=Depends(current_user)):
    rag.delete_file(u["id"], doc_id)
    db.execute("DELETE FROM docs WHERE id=? AND user_id=?", (doc_id, u["id"])); db.commit()
    return {"ok": True}

@app.post("/api/ask")
def ask(b: AskIn, u=Depends(current_user)):
    text, sources = rag.answer(u["id"], b.question)
    return {"answer": text, "sources": sources}

@app.get("/")
def index(): return FileResponse("frontend/index.html")
app.mount("/static", StaticFiles(directory="frontend"), name="static")
