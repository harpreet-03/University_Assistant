"""
router.py — Intent Classifier + Query Router for EduVerse AI

Flow:
  User query
    → classify_intent()   — what kind of question is this?
    → route()             — which DB(s) to query?
    → returns merged context string for LLM

Intent types:
  timetable   → SQL only
  student     → SQL only
  policy      → Vector only
  notice      → Vector only
  hybrid      → SQL + Vector (e.g. "what room is ML class and what's attendance policy?")
  general     → Vector only (fallback)
"""

import re
import sqldb
import vectordb


# ═══════════════════════════════════════════════════════════════
#  Intent signals — keyword sets per intent
# ═══════════════════════════════════════════════════════════════

_TIMETABLE_SIGNALS = {
    "timetable", "schedule", "class", "classes", "lecture", "lectures",
    "timing", "timings", "time", "slot", "when does", "when is",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
    "teaches", "teaching", "taught", "section", "what time",
    "morning", "afternoon", "evening",
}

_LOCATION_SIGNALS = {
    "where", "location", "block", "room", "cabin", "chamber", "seating",
    "which block", "which room", "office", "seat", "allocated",
}

_STUDENT_SIGNALS = {
    "marks", "grade", "grades", "score", "scores", "cgpa", "sgpa",
    "exam result", "examination result", "my marks", "my grade",
    "my performance", "my result", "registration number", "reg no",
}

_POLICY_SIGNALS = {
    "policy", "policies", "rule", "rules", "regulation", "regulations",
    "scholarship", "scholarships", "fee", "fees", "guideline", "guidelines",
    "eligibility", "criteria", "process", "procedure", "how to apply",
    "minimum attendance", "attendance requirement", "detention", "condonation",
    "backlog", "reappear", "ete", "mte", "grading", "academic", "handbook",
    "notice", "circular", "announcement", "admit", "admit card",
    "exam", "examination", "before exam", "during exam", "ume", "umc",
    "attendance", "attendance policy", "attendance sheet", "marking attendance",
}

_GREETING_SIGNALS = {
    "hello", "hi", "hey", "good morning", "good afternoon", "good evening",
    "good night", "thanks", "thank you", "great", "awesome", "helpful",
}


# ═══════════════════════════════════════════════════════════════
#  Classify intent
# ═══════════════════════════════════════════════════════════════

def classify_intent(query):
    """
    Returns one of: 'timetable' | 'student' | 'policy' | 'greeting' | 'hybrid'

    Logic:
    - Count signal matches per category
    - If both timetable+policy signals → hybrid
    - Otherwise return dominant category
    """
    q = query.lower()

    # Tokenise (words + bigrams)
    words  = set(re.findall(r'\b\w+\b', q))
    bigrams = set()
    wlist = q.split()
    for i in range(len(wlist) - 1):
        bigrams.add(f"{wlist[i]} {wlist[i+1]}")
    tokens = words | bigrams

    tt_score  = len(tokens & _TIMETABLE_SIGNALS)
    stu_score = len(tokens & _STUDENT_SIGNALS)
    pol_score = len(tokens & _POLICY_SIGNALS)
    greet     = len(tokens & _GREETING_SIGNALS)

    # Faculty ID or name + day = strong timetable signal
    if re.search(r'\b\d{5}\b', query):
        tt_score += 3
    if re.search(r'\b(monday|tuesday|wednesday|thursday|friday|saturday)\b', q):
        tt_score += 2

    # Registration number = strong student signal
    if re.search(r'\b\d{11}\b', query):
        stu_score += 5

    if greet > 0 and tt_score == 0 and pol_score == 0:
        return "greeting"

    # Hybrid: both timetable and policy questions in one
    if tt_score >= 1 and pol_score >= 2:
        return "hybrid"

    # Check location signals
    loc_score = len(tokens & _LOCATION_SIGNALS)
    
    scores = {"timetable": tt_score, "student": stu_score, "policy": pol_score, "location": loc_score}
    dominant = max(scores, key=scores.get)

    if scores[dominant] == 0:
        return "policy"   # default to vector search

    return dominant


# ═══════════════════════════════════════════════════════════════
#  Route query → context
# ═══════════════════════════════════════════════════════════════

def route(query):
    """
    Main entry point. Returns:
    {
      "context":  str,           # combined context for LLM
      "intent":   str,           # detected intent
      "sources":  list[str],     # source file names
      "hits":     int,           # total results found
      "method":   str,           # "sql" | "vector" | "hybrid" | "greeting"
    }
    """
    intent = classify_intent(query)

    if intent == "greeting":
        return {
            "context": "",
            "intent":  "greeting",
            "sources": [],
            "hits":    0,
            "method":  "greeting",
        }

    if intent == "timetable":
        return _route_sql_timetable(query)

    if intent == "student":
        return _route_sql_student(query)
    
    if intent == "location":
        return _route_sql_location(query)

    if intent == "hybrid":
        return _route_hybrid(query)

    # policy / notice / general → vector
    return _route_vector(query)


# ═══════════════════════════════════════════════════════════════
#  SQL routing
# ═══════════════════════════════════════════════════════════════

def _route_sql_timetable(query):
    # Check if asking for FREE slots
    if re.search(r'\b(free|available|empty)\s+(slot|time|hour)', query.lower()):
        result = sqldb.query_free_slots(query)
    else:
        result = sqldb.query_timetable(query)

    if result:
        return {
            "context": f"[SQL Database — Timetable]\n\n{result}",
            "intent":  "timetable",
            "sources": ["timetable_db"],
            "hits":    1,
            "method":  "sql",
        }

    # SQL found nothing → fallback to vector
    hits = vectordb.search(query, top_k=4)
    return {
        "context":  _build_vector_context(hits),
        "intent":   "timetable",
        "sources":  list({h["source"] for h in hits}),
        "hits":     len(hits),
        "method":   "vector_fallback",
    }


def _route_sql_student(query):
    result = sqldb.query_students(query)

    if result:
        return {
            "context": f"[SQL Database — Students]\n\n{result}",
            "intent":  "student",
            "sources": ["student_db"],
            "hits":    1,
            "method":  "sql",
        }

    return {
        "context":  "",
        "intent":   "student",
        "sources":  [],
        "hits":     0,
        "method":   "sql",
    }


# ═══════════════════════════════════════════════════════════════
#  Vector routing
# ═══════════════════════════════════════════════════════════════

def _route_sql_location(query):
    result = sqldb.query_faculty_location(query)

    if result:
        return {
            "context": f"[SQL Database — Faculty Locations]\n\n{result}",
            "intent":  "location",
            "sources": ["faculty_location_db"],
            "hits":    1,
            "method":  "sql",
        }

    # SQL found nothing → fallback to vector
    hits = vectordb.search(query, top_k=4)
    return {
        "context":  _build_vector_context(hits),
        "intent":   "location",
        "sources":  list({h["source"] for h in hits}),
        "hits":     len(hits),
        "method":   "vector_fallback",
    }


def _route_vector(query):
    hits = vectordb.search(query, top_k=6)
    return {
        "context":  _build_vector_context(hits),
        "intent":   "policy",
        "sources":  list(dict.fromkeys(h["source"] for h in hits)),
        "hits":     len(hits),
        "method":   "vector",
    }


# ═══════════════════════════════════════════════════════════════
#  Hybrid routing (SQL + Vector merged)
# ═══════════════════════════════════════════════════════════════

def _route_hybrid(query):
    sql_result = sqldb.query_timetable(query)
    vec_hits   = vectordb.search(query, top_k=4)

    parts = []
    sources = []

    if sql_result:
        parts.append(f"[SQL Database — Timetable]\n\n{sql_result}")
        sources.append("timetable_db")

    if vec_hits:
        parts.append(_build_vector_context(vec_hits))
        sources.extend(h["source"] for h in vec_hits)

    return {
        "context": "\n\n" + "═"*50 + "\n\n".join(parts) if parts else "",
        "intent":  "hybrid",
        "sources": list(dict.fromkeys(sources)),
        "hits":    (1 if sql_result else 0) + len(vec_hits),
        "method":  "hybrid",
    }


# ═══════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════

def _build_vector_context(hits):
    if not hits:
        return ""
    parts = []
    for i, h in enumerate(hits, 1):
        parts.append(
            f"[Document {i} — {h['source']} | relevance: {h['score']:.2f}]\n"
            f"{h['text']}"
        )
    return "\n\n---\n\n".join(parts)