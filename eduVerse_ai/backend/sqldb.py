"""
sqldb.py — SQLite structured database for EduVerse AI

Handles ALL tabular data: timetables, marks, attendance CSVs.
Exact SQL lookups — no embeddings, no thresholds, always accurate.

Tables:
  timetable  — one row per class slot
  students   — from marks/attendance CSVs (if uploaded)

Query builder:
  Natural language → SQL via keyword extraction
  "Sheetal Monday" → SELECT * FROM timetable WHERE faculty_name LIKE '%Sheetal%' AND day='Monday'
"""

import os
import re
import sqlite3
from pathlib import Path

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "structured.db")


# ═══════════════════════════════════════════════════════════════
#  Connection helper
# ═══════════════════════════════════════════════════════════════

def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row   # access columns by name
    return con


# ═══════════════════════════════════════════════════════════════
#  Schema setup
# ═══════════════════════════════════════════════════════════════

def init():
    """Create tables if they don't exist."""
    with _conn() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS timetable (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                faculty_id  TEXT,
                faculty_name TEXT,
                day         TEXT,
                time_slot   TEXT,
                course_code TEXT,
                course_name TEXT,
                section     TEXT,
                room        TEXT,
                class_type  TEXT,
                source_file TEXT
            );

            CREATE TABLE IF NOT EXISTS students (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                reg_no      TEXT,
                name        TEXT,
                course_code TEXT,
                course_name TEXT,
                marks       REAL,
                grade       TEXT,
                attendance  REAL,
                semester    TEXT,
                source_file TEXT
            );
        """)
        # Indexes for fast lookup
        con.executescript("""
            CREATE INDEX IF NOT EXISTS idx_tt_faculty  ON timetable(faculty_name);
            CREATE INDEX IF NOT EXISTS idx_tt_day      ON timetable(day);
            CREATE INDEX IF NOT EXISTS idx_tt_course   ON timetable(course_code);
            CREATE INDEX IF NOT EXISTS idx_tt_fid      ON timetable(faculty_id);
            CREATE INDEX IF NOT EXISTS idx_st_reg      ON students(reg_no);
            CREATE INDEX IF NOT EXISTS idx_st_name     ON students(name);
        """)


# ═══════════════════════════════════════════════════════════════
#  Insert timetable rows
# ═══════════════════════════════════════════════════════════════

def insert_timetable(rows, source_file):
    """
    rows: list of dicts with keys matching timetable columns
    Deletes existing rows from this source first (safe re-upload).
    """
    init()
    with _conn() as con:
        con.execute("DELETE FROM timetable WHERE source_file = ?", (source_file,))
        con.executemany("""
            INSERT INTO timetable
              (faculty_id, faculty_name, day, time_slot, course_code,
               course_name, section, room, class_type, source_file)
            VALUES
              (:faculty_id, :faculty_name, :day, :time_slot, :course_code,
               :course_name, :section, :room, :class_type, :source_file)
        """, [{**r, "source_file": source_file} for r in rows])
    return len(rows)


def insert_students(rows, source_file):
    """rows: list of dicts with student data."""
    init()
    with _conn() as con:
        con.execute("DELETE FROM students WHERE source_file = ?", (source_file,))
        con.executemany("""
            INSERT INTO students
              (reg_no, name, course_code, course_name, marks, grade,
               attendance, semester, source_file)
            VALUES
              (:reg_no, :name, :course_code, :course_name, :marks, :grade,
               :attendance, :semester, :source_file)
        """, [{**r, "source_file": source_file} for r in rows])
    return len(rows)


def delete_by_source(source_file):
    """Remove all rows from a specific uploaded file."""
    init()
    with _conn() as con:
        con.execute("DELETE FROM timetable WHERE source_file = ?", (source_file,))
        con.execute("DELETE FROM students  WHERE source_file = ?", (source_file,))


# ═══════════════════════════════════════════════════════════════
#  Query: timetable
# ═══════════════════════════════════════════════════════════════

_DAYS = {
    "monday": "Monday", "mon": "Monday",
    "tuesday": "Tuesday", "tue": "Tuesday", "tues": "Tuesday",
    "wednesday": "Wednesday", "wed": "Wednesday",
    "thursday": "Thursday", "thu": "Thursday", "thur": "Thursday", "thurs": "Thursday",
    "friday": "Friday", "fri": "Friday",
    "saturday": "Saturday", "sat": "Saturday",
    "sunday": "Sunday", "sun": "Sunday",
}

_TIME_PATTERNS = [
    # "9am", "10am", "9:00", "09:00-10:00"
    (r'\b(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})', "range"),
    (r'\b(\d{1,2})\s*am\b',  "hour_am"),
    (r'\b(\d{1,2})\s*pm\b',  "hour_pm"),
    (r'\b(\d{1,2}):(\d{2})\b', "hhmm"),
]


def _extract_time_filter(q):
    """Extract a time filter string from query, e.g. '09:00' or '14:00'."""
    q = q.lower()
    for pattern, kind in _TIME_PATTERNS:
        m = re.search(pattern, q)
        if not m:
            continue
        if kind == "range":
            return m.group(0).replace(" ", "")
        elif kind == "hour_am":
            h = int(m.group(1))
            return f"{h:02d}:"
        elif kind == "hour_pm":
            h = int(m.group(1))
            if h < 12: h += 12
            return f"{h:02d}:"
        elif kind == "hhmm":
            return f"{int(m.group(1)):02d}:{m.group(2)}"
    return None


def query_timetable(query):
    """
    Convert natural language query to SQL and return formatted result string.
    Returns None if no results found.
    """
    init()
    q = query.lower()

    conditions = []
    params     = []

    # ── Day detection ─────────────────────────────────────────
    detected_day = None
    for word, day in _DAYS.items():
        if re.search(rf'\b{word}\b', q):
            detected_day = day
            break
    if detected_day:
        conditions.append("day = ?")
        params.append(detected_day)
    # Day is OPTIONAL — if not specified, return all days

    # ── Time detection ────────────────────────────────────────
    time_hint = _extract_time_filter(q)
    if time_hint:
        conditions.append("time_slot LIKE ?")
        params.append(f"%{time_hint}%")

    # ── Faculty name / ID detection ───────────────────────────
    # First try ID (5-digit number)
    fid_match = re.search(r'\b(\d{5})\b', query)
    if fid_match:
        conditions.append("faculty_id = ?")
        params.append(fid_match.group(1))
    else:
        # Try known name fragments — extract capitalised words or quoted names
        # Remove common filler words
        stop = {"tell","me","the","show","what","is","of","on","for","schedule",
                "timetable","class","classes","today","time","when","does","teach",
                "teaching","courses","monday","tuesday","wednesday","thursday",
                "friday","saturday","sunday","sir","mam","ma'am","madam","dr","prof",
                "professor","a","an","and","or","in","at","by","from","to","with",
                "about","room","section","which"}
        # Pull possible name tokens (capitalised or after "of"/"for")
        name_tokens = []
        # Strategy 1: extract ALL words between keywords and end/day
        # "dalwinder sir" → captures "dalwinder sir"
        # "dr anshu schedule" → captures "anshu" (after stripping "dr")
        clean_q = re.sub(r'\b(dr|prof|mr|ms|mrs)\.?\s+', '', query, flags=re.I)
        
        # Try pattern: (optional trigger) + NAME + (day|timetable|end)
        # Matches: "dalwinder sir", "manik timetable", "dr anshu"
        m = re.search(
            r'(?:of|for|schedule|timetable|show|tell|free\s+slot)?\s*'
            r'([a-zA-Z][a-zA-Z\s]{2,40}?)'
            r'(?:\s+sir|\s+mam|\s+madam|\s+on\b|\s+and|\s+timetable|'
            r'\s+monday|\s+tuesday|\s+wednesday|\s+thursday|'
            r'\s+friday|\s+saturday|\s+sunday|\s*$)',
            clean_q, re.I
        )
        if m:
            candidate = m.group(1).strip()
            name_tokens = [w for w in candidate.split()
                          if w.lower() not in stop and len(w) > 1]

        if not name_tokens:
            # Strategy 2: just grab all capitalized words (after removing titles)
            name_tokens = [w for w in clean_q.split()
                          if w and w[0].isupper() and w.lower() not in stop and len(w) > 2]

        if name_tokens:
            # Fuzzy name matching: search for ANY token in faculty_name
            # This allows "dalwinder" to match "Dr. Dalwinder Singh"
            # and "manik sir" to match "Dr. Manik"
            name_conds = " OR ".join(["LOWER(faculty_name) LIKE ?" for _ in name_tokens])
            conditions.append(f"({name_conds})")
            params.extend([f"%{t.lower()}%" for t in name_tokens])

    # ── Course detection ──────────────────────────────────────
    course_m = re.search(r'\b([A-Z]{2,5}\d{3,4})\b', query)
    if course_m:
        conditions.append("(course_code = ? OR course_name LIKE ?)")
        params.extend([course_m.group(1), f"%{course_m.group(1)}%"])
    else:
        # Course name keywords
        course_keywords = {
            "machine learning": "Machine Learning",
            "deep learning": "Deep Learning",
            "programming": "Problem Solving",
            "problem solving": "Problem Solving",
            "research": "Research Methodology",
            "values": "Universal Human Values",
            "religion": "Universal Human Values",
            "internship": "Internship",
            "capstone": "Capstone",
            "project": "Capstone",
        }
        for kw, cname in course_keywords.items():
            if kw in q:
                conditions.append("course_name LIKE ?")
                params.append(f"%{cname}%")
                break

    # ── Room detection ────────────────────────────────────────
    room_m = re.search(r'\b(\d{2,3}-\d{3,4}[A-Z]?)\b', query)
    if room_m:
        conditions.append("room = ?")
        params.append(room_m.group(1))

    # ── Section detection ─────────────────────────────────────
    section_m = re.search(r'\b(K2[2-5][A-Z]{2}|[A-Z]{2,3}\d{3,4}|\d{3}[A-Z]{2})\b', query)
    if section_m:
        conditions.append("section LIKE ?")
        params.append(f"%{section_m.group(1)}%")

    if not conditions:
        return None   # can't form a meaningful query

    sql = "SELECT * FROM timetable WHERE " + " AND ".join(conditions)
    sql += " ORDER BY day, time_slot LIMIT 50"

    with _conn() as con:
        rows = con.execute(sql, params).fetchall()

    if not rows:
        return None

    return _format_timetable_results(rows, detected_day)



def query_free_slots(query):
    """Find FREE time slots for a faculty member on a given day."""
    init()
    q = query.lower()
    
    # Detect day
    detected_day = None
    for word, day in _DAYS.items():
        if re.search(rf'\b{word}\b', q):
            detected_day = day
            break
    
    if not detected_day:
        return None
    
    # Detect faculty
    fid_match = re.search(r'\b(\d{5})\b', query)
    name_tokens = []
    
    if not fid_match:
        clean_q = re.sub(r'\b(dr|prof|mr|ms|mrs)\.?\s*', '', query, flags=re.I)
        m = re.search(
            r'(?:of|for|schedule|timetable|free|slots)\s+([a-zA-Z][a-zA-Z\s]{2,35})'
            r'(?:\s+on\b|\s+monday|\s+tuesday|\s+wednesday|'
            r'\s+thursday|\s+friday|\s+saturday|\s+sunday|\s*$)',
            clean_q, re.I
        )
        if m:
            candidate = m.group(1).strip()
            stop = {'tell','me','the','show','what','is','of','on','for','schedule',
                   'timetable','class','classes','today','time','when','does','teach',
                   'free','slots','available','empty'}
            name_tokens = [w for w in candidate.split()
                          if w.lower() not in stop and len(w) > 2]
    
    if not name_tokens and not fid_match:
        return None
    
    # Build SQL
    conditions = [f"day = ?"]
    params = [detected_day]
    
    if fid_match:
        conditions.append("faculty_id = ?")
        params.append(fid_match.group(1))
    elif name_tokens:
        name_conds = " OR ".join(["LOWER(faculty_name) LIKE ?" for _ in name_tokens])
        conditions.append(f"({name_conds})")
        params.extend([f"%{t.lower()}%" for t in name_tokens])
    
    sql = "SELECT * FROM timetable WHERE " + " AND ".join(conditions)
    sql += " ORDER BY time_slot"
    
    with _conn() as con:
        rows = con.execute(sql, params).fetchall()
    
    if not rows:
        return None
    
    # Parse occupied slots
    occupied = []
    for r in rows:
        ts = r['time_slot']
        # Parse "09:00-10:00" or "09-10 AM"
        m = re.match(r'(\d{1,2}):?(\d{2})?\s*-\s*(\d{1,2}):?(\d{2})?', ts)
        if m:
            sh = int(m.group(1))
            sm = int(m.group(2)) if m.group(2) else 0
            eh = int(m.group(3))
            em = int(m.group(4)) if m.group(4) else 0
            occupied.append((sh * 60 + sm, eh * 60 + em))
    
    # Standard working hours: 8:00 AM - 6:00 PM
    work_start = 8 * 60   # 480 min
    work_end   = 18 * 60  # 1080 min
    
    occupied.sort()
    free = []
    current = work_start
    
    for start, end in occupied:
        if start > current:
            free.append((current, start))
        current = max(current, end)
    
    if current < work_end:
        free.append((current, work_end))
    
    if not free:
        fname = rows[0]['faculty_name']
        return f"No free slots for {fname} on {detected_day} (fully scheduled 8 AM - 6 PM)."
    
    # Format - improved readability
    fname = rows[0]['faculty_name']
    fid   = rows[0]['faculty_id']
    
    lines = [
        f"📅 {fname}'s Free Slots on {detected_day}:",
        ""
    ]
    
    total_hours = 0
    for start_min, end_min in free:
        sh, sm = divmod(start_min, 60)
        eh, em = divmod(end_min, 60)
        duration = (end_min - start_min) / 60
        total_hours += duration
        
        # Convert to 12-hour format
        start_period = "AM" if sh < 12 else "PM"
        end_period   = "AM" if eh < 12 else "PM"
        start_h = sh if sh <= 12 else sh - 12
        end_h   = eh if eh <= 12 else eh - 12
        if start_h == 0: start_h = 12
        if end_h == 0: end_h = 12
        
        lines.append(
            f"  • {start_h:02d}:{sm:02d} {start_period} - {end_h:02d}:{em:02d} {end_period}  "
            f"({duration:.1f} hour{'s' if duration != 1 else ''})"
        )
    
    lines.append("")
    lines.append(f"Total free time: {total_hours:.1f} hours")
    
    return "\n".join(lines)


def _format_timetable_results(rows, day_filter=None):
    """Format SQL rows into readable text for the LLM."""
    if not rows:
        return None

    # Group by faculty then day
    from collections import defaultdict
    faculty_days = defaultdict(lambda: defaultdict(list))
    for r in rows:
        faculty_days[f"{r['faculty_name']} (ID: {r['faculty_id']})"][r['day']].append(r)

    parts = []
    day_order = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday","Special"]

    for faculty, days in faculty_days.items():
        lines = [f"📅 Timetable — {faculty}"]
        if day_filter:
            lines[0] += f" | {day_filter}"

        for day in day_order:
            slots = days.get(day)
            if not slots:
                continue
            lines.append(f"\n{day}:")
            for s in sorted(slots, key=lambda x: x['time_slot']):
                course = (f"{s['course_code']} - {s['course_name']}"
                         if s['course_name'] and s['course_name'] != s['course_code']
                         else s['course_code'])
                lines.append(
                    f"  {s['time_slot']:14s} | {course:45s} | "
                    f"Section: {s['section']:12s} | Room: {s['room']:10s} | {s['class_type']}"
                )
        parts.append("\n".join(lines))

    return "\n\n".join(parts)


# ═══════════════════════════════════════════════════════════════
#  Query: students
# ═══════════════════════════════════════════════════════════════

def query_students(query):
    """Query student marks/attendance data."""
    init()
    q = query.lower()
    conditions, params = [], []

    # Registration number
    reg_m = re.search(r'\b(\d{11})\b', query)
    if reg_m:
        conditions.append("reg_no = ?")
        params.append(reg_m.group(1))

    # Student name
    stop = {"student","marks","attendance","grade","show","tell","me","the","of","for","what","is"}
    name_tokens = [w for w in query.split()
                  if w[0].isupper() and w.lower() not in stop and len(w) > 2]
    if name_tokens and not reg_m:
        name_conds = " OR ".join(["name LIKE ?" for _ in name_tokens])
        conditions.append(f"({name_conds})")
        params.extend([f"%{t}%" for t in name_tokens])

    # Course
    course_m = re.search(r'\b([A-Z]{2,5}\d{3,4})\b', query)
    if course_m:
        conditions.append("course_code = ?")
        params.append(course_m.group(1))

    if not conditions:
        return None

    sql = "SELECT * FROM students WHERE " + " AND ".join(conditions) + " LIMIT 20"
    with _conn() as con:
        rows = con.execute(sql, params).fetchall()

    if not rows:
        return None

    lines = ["Student Records:"]
    for r in rows:
        lines.append(
            f"  {r['name']} ({r['reg_no']}) | "
            f"Course: {r['course_code']} | "
            f"Marks: {r['marks']} | Grade: {r['grade']} | "
            f"Attendance: {r['attendance']}%"
        )
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
#  Stats
# ═══════════════════════════════════════════════════════════════

def stats():
    init()
    try:
        with _conn() as con:
            tt  = con.execute("SELECT COUNT(*) FROM timetable").fetchone()[0]
            stu = con.execute("SELECT COUNT(*) FROM students").fetchone()[0]
            fac = con.execute("SELECT COUNT(DISTINCT faculty_name) FROM timetable").fetchone()[0]
        return {"timetable_rows": tt, "student_rows": stu, "faculty_count": fac}
    except Exception:
        return {"timetable_rows": 0, "student_rows": 0, "faculty_count": 0}