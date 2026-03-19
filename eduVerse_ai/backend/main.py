"""
main.py — EduVerse AI FastAPI backend (Hybrid RAG)

Routes:
  POST /upload           — upload file, parse → SQL (xlsx) or Vector (pdf/docx)
  GET  /files            — list all indexed files
  DELETE /files/{name}   — delete a file
  POST /chat             — Hybrid RAG question answering
  GET  /health           — system status

Run:
  uvicorn main:app --reload --port 8000
"""

import os
import json
import uuid
import time
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv() # Load from .env

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

import parsers
import auth
import users
import audit
import vectordb
import sqldb
import router
import llm

UPLOAD_DIR = Path(__file__).parent.parent / "uploads"
META_FILE  = Path(__file__).parent.parent / "files.json"
UPLOAD_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("eduverse")

app = FastAPI(title="EduVerse AI", version="3.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

sessions = {}


# ── Helpers ──────────────────────────────────────────────────

def load_meta():
    if META_FILE.exists():
        return json.loads(META_FILE.read_text())
    return []

def save_meta(data):
    META_FILE.write_text(json.dumps(data, indent=2, default=str))

def auto_detect_type(filename):
    ext  = Path(filename).suffix.lower()
    name = filename.lower()
    if ext in (".xlsx", ".xls"):
        return "timetable"
    if any(w in name for w in ("rule", "policy", "regulation", "academic", "attendance",
                                "scholarship", "guideline", "process", "sop",
                                "fee", "exam", "reappear", "etp", "marks", "result")):
        return "policy"
    if any(w in name for w in ("notice", "circular", "announcement")):
        return "notice"
    return "general"


# ── Routes ───────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status": "ok",
        "llm":    llm.health(),
        "db":     vectordb.stats(),
        "sql":    sqldb.stats(),
    }




# ── Authentication Routes ────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str

class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "student"
    email: Optional[str] = None
    full_name: Optional[str] = None

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@app.post("/auth/login")
def login(req: LoginRequest, request: Request):
    """Authenticate user and return JWT token."""
    user = users.authenticate_user(req.username, req.password)
    if not user:
        raise HTTPException(401, detail="Invalid username or password")
    
    # Create JWT token
    token = auth.create_jwt(user["id"], user["username"], user["role"])
    
    # Log login
    ip = request.client.host if request.client else None
    audit.log_action(user["id"], "login", ip_address=ip)
    
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user
    }


@app.get("/auth/me")
async def get_me(request: Request):
    """Get current user info from JWT token."""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(401, detail="Not authenticated")
    
    token = auth_header.replace("Bearer ", "")
    user_data = auth.verify_jwt(token)
    
    if not user_data:
        raise HTTPException(401, detail="Invalid or expired token")
    
    # Get full user info from database
    user = users.get_user(user_data["user_id"])
    if not user or not user["is_active"]:
        raise HTTPException(401, detail="User not found or inactive")
    
    return {"user": user}


@app.post("/auth/logout")
async def logout(request: Request):
    """Logout (client should discard token)."""
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.replace("Bearer ", "")
        user_data = auth.verify_jwt(token)
        if user_data:
            ip = request.client.host if request.client else None
            audit.log_action(user_data["user_id"], "logout", ip_address=ip)
    
    return {"ok": True}


@app.post("/auth/change-password")
async def change_password(req: ChangePasswordRequest, request: Request):
    """Change current user's password."""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(401, detail="Not authenticated")
    
    token = auth_header.replace("Bearer ", "")
    user_data = auth.verify_jwt(token)
    
    if not user_data:
        raise HTTPException(401, detail="Invalid token")
    
    # Verify current password
    user = users.authenticate_user(user_data["username"], req.current_password)
    if not user:
        raise HTTPException(401, detail="Current password is incorrect")
    
    # Change password
    try:
        users.change_password(user_data["user_id"], req.new_password)
        ip = request.client.host if request.client else None
        audit.log_action(user_data["user_id"], "change_password", ip_address=ip)
        return {"ok": True, "message": "Password changed successfully"}
    except ValueError as e:
        raise HTTPException(400, detail=str(e))


# ── User Management Routes (Admin Only) ──────────────────────────

@app.get("/users")
@auth.require_auth(["admin"])
async def list_all_users(request: Request):
    """List all users (admin only)."""
    all_users = users.list_users(include_inactive=True)
    return {"users": all_users}


@app.post("/users")
@auth.require_auth(["admin"])
async def create_new_user(req: CreateUserRequest, request: Request):
    """Create a new user (admin only)."""
    try:
        user = users.create_user(
            username=req.username,
            password=req.password,
            role=req.role,
            email=req.email,
            full_name=req.full_name,
            created_by=request.state.user["user_id"]
        )
        
        ip = request.client.host if request.client else None
        audit.log_action(
            request.state.user["user_id"], 
            "create_user", 
            req.username,
            ip
        )
        
        return {"ok": True, "user": user}
    except ValueError as e:
        raise HTTPException(400, detail=str(e))


@app.delete("/users/{user_id}")
@auth.require_auth(["admin"])
async def delete_user_route(user_id: int, request: Request):
    """Delete a user (admin only)."""
    # Prevent self-deletion
    if user_id == request.state.user["user_id"]:
        raise HTTPException(400, detail="Cannot delete your own account")
    
    user = users.get_user(user_id)
    if not user:
        raise HTTPException(404, detail="User not found")
    
    users.delete_user(user_id)
    
    ip = request.client.host if request.client else None
    audit.log_action(
        request.state.user["user_id"],
        "delete_user",
        user["username"],
        ip
    )
    
    return {"ok": True, "deleted": user["username"]}


@app.get("/audit")
@auth.require_auth(["admin"])
async def get_audit_logs_route(request: Request, limit: int = 100, offset: int = 0):
    """Get audit logs (admin only)."""
    logs = audit.get_audit_logs(limit=limit, offset=offset)
    summary = audit.get_audit_summary()
    return {"logs": logs, "summary": summary}


@app.post("/upload")
@auth.require_auth(["admin"])
async def upload(request: Request, file: UploadFile = File(...), doc_type: str = Form("auto")):
    allowed = {".pdf", ".xlsx", ".xls", ".csv", ".txt", ".docx", ".doc"}
    ext = Path(file.filename).suffix.lower()
    if ext not in allowed:
        raise HTTPException(400, f"File type '{ext}' not supported.")

    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 50 MB).")

    save_path = UPLOAD_DIR / file.filename
    save_path.write_bytes(content)

    if doc_type == "auto":
        doc_type = auto_detect_type(file.filename)

    count = 0

    # ── XLSX → SQL (structured) ───────────────────────────────
    if ext in (".xlsx", ".xls"):
        try:
            # Try timetable format first
            rows = parsers.parse_xlsx_to_rows(str(save_path))
            if rows:
                count = sqldb.insert_timetable(rows, file.filename)
                log.info(f"UPLOAD SQL   {file.filename}  rows={count} (timetable)")
            else:
                # Try faculty allocation format
                rows = parsers.parse_faculty_allocation_to_rows(str(save_path))
                if rows:
                    count = sqldb.insert_faculty_allocation(rows, file.filename)
                    log.info(f"UPLOAD SQL   {file.filename}  rows={count} (allocation)")
                else:
                    raise ValueError("Not recognized timetable or allocation format")
        except Exception as e:
            # Fallback: parse as text chunks for vector DB
            log.warning(f"xlsx SQL insert failed ({e}), falling back to vector")
            try:
                chunks = parsers.parse_file(str(save_path))
                count  = vectordb.save(chunks, doc_type, file.filename)
                log.info(f"UPLOAD VEC   {file.filename}  chunks={count}")
            except Exception as e2:
                save_path.unlink(missing_ok=True)
                raise HTTPException(500, f"Parsing failed: {e2}")

    # ── CSV → SQL (student data) or Vector ────────────────────
    elif ext == ".csv":
        try:
            chunks = parsers.parse_file(str(save_path))
            count  = vectordb.save(chunks, doc_type, file.filename)
            log.info(f"UPLOAD VEC   {file.filename}  chunks={count}")
        except Exception as e:
            save_path.unlink(missing_ok=True)
            raise HTTPException(500, f"Parsing failed: {e}")

    # ── PDF / DOCX / TXT → Vector ─────────────────────────────
    else:
        try:
            chunks = parsers.parse_file(str(save_path))
            if not chunks:
                save_path.unlink(missing_ok=True)
                raise HTTPException(422, "No text could be extracted.")
            count = vectordb.save(chunks, doc_type, file.filename)
            log.info(f"UPLOAD VEC   {file.filename}  chunks={count}")
        except HTTPException:
            raise
        except Exception as e:
            save_path.unlink(missing_ok=True)
            raise HTTPException(500, f"Parsing failed: {e}")

    if count == 0:
        save_path.unlink(missing_ok=True)
        raise HTTPException(422, "No data could be extracted from this file.")

    meta = load_meta()
    meta = [m for m in meta if m["filename"] != file.filename]
    meta.append({
        "filename": file.filename,
        "doc_type": doc_type,
        "chunks":   count,
        "size_kb":  round(len(content) / 1024, 1),
        "storage":  "sql" if ext in (".xlsx", ".xls") and doc_type == "timetable" else "vector",
    })
    save_meta(meta)
    
    # Log upload action
    ip = request.client.host if request.client else None
    audit.log_action(request.state.user["user_id"], "upload", file.filename, ip)

    return {"ok": True, "filename": file.filename, "doc_type": doc_type, "chunks": count}


@app.get("/files")
def list_files():
    return {"files": load_meta()}


@app.delete("/files/{filename}")
@auth.require_auth(["admin"])
async def delete_file(filename: str, request: Request):
    meta   = load_meta()
    record = next((m for m in meta if m["filename"] == filename), None)
    if not record:
        raise HTTPException(404, "File not found.")
    (UPLOAD_DIR / filename).unlink(missing_ok=True)
    sqldb.delete_by_source(filename)
    vectordb.delete(filename, record["doc_type"])
    save_meta([m for m in meta if m["filename"] != filename])
    
    # Log delete action
    ip = request.client.host if request.client else None
    audit.log_action(request.state.user["user_id"], "delete", filename, ip)
    
    return {"ok": True, "deleted": filename}


class ChatRequest(BaseModel):
    message:    str
    session_id: Optional[str]   = None
    min_score:  Optional[float] = None


@app.post("/chat")
def chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(400, "Message cannot be empty.")

    sid     = req.session_id or str(uuid.uuid4())
    history = sessions.get(sid, [])
    t0      = time.time()

    # ── Route query ───────────────────────────────────────────
    result = router.route(req.message)

    log.info(
        f"QUERY  intent={result['intent']:10s} method={result['method']:15s} "
        f"hits={result['hits']}  '{req.message[:55]}'"
    )

    # ── Ask LLM ───────────────────────────────────────────────
    answer = llm.ask(req.message, result["context"], history)

    # ── Update session ────────────────────────────────────────
    history.append({"role": "user",      "content": req.message})
    history.append({"role": "assistant", "content": answer})
    sessions[sid] = history[-20:]

    return {
        "answer":     answer,
        "session_id": sid,
        "sources":    result["sources"],
        "hits":       result["hits"],
        "intent":     result["intent"],
        "method":     result["method"],
        "no_context": result["hits"] == 0 and result["intent"] != "greeting",
        "ms":         round((time.time() - t0) * 1000),
    }


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    sid       = req.session_id or str(uuid.uuid4())
    history   = sessions.get(sid, [])
    result    = router.route(req.message)
    collected = []

    log.info(f"STREAM intent={result['intent']} method={result['method']} hits={result['hits']}")

    async def generate():
        yield f"data: {json.dumps({'type':'start','session_id':sid,'hits':result['hits'],'intent':result['intent']})}\n\n"
        async for token in llm.ask_stream(req.message, result["context"], history):
            collected.append(token)
            yield f"data: {json.dumps({'type':'token','content':token})}\n\n"
        full = "".join(collected)
        history.append({"role": "user",      "content": req.message})
        history.append({"role": "assistant", "content": full})
        sessions[sid] = history[-20:]
        yield f"data: {json.dumps({'type':'done','sources':result['sources']})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── Static frontend ──────────────────────────────────────────
from fastapi.staticfiles import StaticFiles
frontend_path = Path(__file__).parent.parent / "frontend"
app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")