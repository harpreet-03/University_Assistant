"""
vectordb.py
Local vector database — ChromaDB + sentence-transformers.
NO API KEY needed. Downloads embedding model once (~90 MB), then works offline.

Collections:
  timetables  → XLSX timetable files
  policies    → PDF/DOCX rules, regulations, scholarships
  notices     → Circulars, announcements
  general     → CSV, TXT, anything else

WHY per-collection thresholds:
  all-MiniLM-L6-v2 scores SHORT structured chunks (timetables) lower
  than LONG dense text (policy docs) even when the match is correct.
  A single global threshold either:
    - too high → filters out valid timetable hits  (the bug we had)
    - too low  → lets garbage policy chunks pollute timetable answers
  Solution: each collection gets its own min_score tuned to its content type.
"""

import os
import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

DB_PATH     = os.path.join(os.path.dirname(__file__), "..", "db")
EMBED_MODEL = "all-MiniLM-L6-v2"

TYPE_TO_COLLECTION = {
    "timetable": "timetables",
    "policy":    "policies",
    "notice":    "notices",
    "general":   "general",
}

# ── Per-collection minimum relevance thresholds ───────────────
# Timetable chunks are short & structured → embeddings score lower
# Policy chunks are long & dense → embeddings score higher
# Calibrated against real LPU documents with all-MiniLM-L6-v2
MIN_SCORE = {
    "timetables": 0.18,   # short structured rows — need low threshold
    "policies":   0.32,   # long dense text — keep strict to avoid hallucination
    "notices":    0.22,   # medium length announcements
    "general":    0.20,   # catch-all
}


def _col(name):
    os.makedirs(DB_PATH, exist_ok=True)
    client = chromadb.PersistentClient(path=os.path.abspath(DB_PATH))
    ef     = SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL)
    return client.get_or_create_collection(
        name=name,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )


def save(chunks, doc_type, filename):
    """
    Save text chunks into the correct collection.
    chunks   : list[str]  — from parsers.py
    doc_type : str        — "timetable" | "policy" | "notice" | "general"
    filename : str        — original filename, stored as metadata
    """
    col_name  = TYPE_TO_COLLECTION.get(doc_type, "general")
    col       = _col(col_name)
    ids       = [f"{filename}::{i}" for i in range(len(chunks))]
    metadatas = [{"source": filename, "doc_type": doc_type} for _ in chunks]
    col.upsert(ids=ids, documents=chunks, metadatas=metadatas)
    return len(chunks)


def delete(filename, doc_type):
    col_name = TYPE_TO_COLLECTION.get(doc_type, "general")
    try:
        _col(col_name).delete(where={"source": filename})
    except Exception:
        pass


def search(query, top_k=6, min_score=None):
    """
    Semantic search across ALL collections.
    Returns list of dicts: [{text, source, doc_type, score}, ...]
    sorted best-first, filtered by per-collection min_score.

    min_score: optional float override — applies to ALL collections.
               Use only for debugging (e.g. pass 0.0 to see all raw scores).
    """
    results = []

    for col_name in TYPE_TO_COLLECTION.values():
        try:
            col   = _col(col_name)
            count = col.count()
            if count == 0:
                continue

            n = min(top_k, count)
            r = col.query(
                query_texts=[query],
                n_results=n,
                include=["documents", "metadatas", "distances"],
            )

            # Use override if given, else use per-collection threshold
            threshold = min_score if min_score is not None else MIN_SCORE.get(col_name, 0.20)

            for doc, meta, dist in zip(
                r["documents"][0], r["metadatas"][0], r["distances"][0]
            ):
                score = round(1.0 - dist, 4)
                if score >= threshold:
                    results.append({
                        "text":     doc,
                        "source":   meta.get("source", ""),
                        "doc_type": meta.get("doc_type", ""),
                        "score":    score,
                    })

        except Exception:
            continue

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


def stats():
    out = {}
    for label, col_name in TYPE_TO_COLLECTION.items():
        try:
            out[label] = _col(col_name).count()
        except Exception:
            out[label] = 0
    return out