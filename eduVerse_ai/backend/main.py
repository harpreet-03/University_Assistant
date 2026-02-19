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

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

import parsers
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


@app.post("/upload")
async def upload(file: UploadFile = File(...), doc_type: str = Form("auto")):
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
            rows = parsers.parse_xlsx_to_rows(str(save_path))
            if rows:
                count = sqldb.insert_timetable(rows, file.filename)
                log.info(f"UPLOAD SQL   {file.filename}  rows={count}")
            else:
                # Flat format not detected — try CSV-style marks data
                raise ValueError("Not flat timetable format")
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

    return {"ok": True, "filename": file.filename, "doc_type": doc_type, "chunks": count}


@app.get("/files")
def list_files():
    return {"files": load_meta()}


@app.delete("/files/{filename}")
def delete_file(filename: str):
    meta   = load_meta()
    record = next((m for m in meta if m["filename"] == filename), None)
    if not record:
        raise HTTPException(404, "File not found.")
    (UPLOAD_DIR / filename).unlink(missing_ok=True)
    sqldb.delete_by_source(filename)
    vectordb.delete(filename, record["doc_type"])
    save_meta([m for m in meta if m["filename"] != filename])
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