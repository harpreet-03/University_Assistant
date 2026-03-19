"""
users.py — User Management for EduVerse AI

Database operations for users table.
"""

import sqlite3
from datetime import datetime
from typing import Optional, List, Dict
from pathlib import Path

import auth

DB_PATH = Path(__file__).parent.parent / "db" / "structured.db"


def _conn():
    """Get database connection with row factory."""
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    return con


def init_users_table():
    """Create users and audit_log tables if they don't exist."""
    with _conn() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                username        TEXT UNIQUE NOT NULL,
                password_hash   TEXT NOT NULL,
                email           TEXT,
                full_name       TEXT,
                role            TEXT NOT NULL DEFAULT 'student',
                is_active       INTEGER DEFAULT 1,
                created_at      TEXT NOT NULL,
                created_by      INTEGER,
                last_login      TEXT,
                FOREIGN KEY (created_by) REFERENCES users(id)
            );
            
            CREATE TABLE IF NOT EXISTS audit_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER,
                action          TEXT NOT NULL,
                resource        TEXT,
                ip_address      TEXT,
                timestamp       TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            
            CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
            CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
            CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id);
            CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);
        """)


def create_user(username: str, password: str, role: str = "student", 
                email: str = None, full_name: str = None, created_by: int = None) -> Dict:
    """
    Create a new user.
    
    Args:
        username: Unique username
        password: Plain text password (will be hashed)
        role: 'admin', 'faculty', or 'student'
        email: Optional email address
        full_name: Optional full name
        created_by: User ID of creator (for audit)
    
    Returns:
        Dict with user info (without password hash)
    
    Raises:
        ValueError: If username exists or validation fails
    """
    # Validate username
    valid, error = auth.validate_username(username)
    if not valid:
        raise ValueError(error)
    
    # Validate password
    valid, error = auth.validate_password(password)
    if not valid:
        raise ValueError(error)
    
    # Validate role
    if role not in ("admin", "faculty", "student"):
        raise ValueError("Role must be 'admin', 'faculty', or 'student'")
    
    # Hash password
    password_hash = auth.hash_password(password)
    
    init_users_table()
    
    with _conn() as con:
        # Check if username exists
        existing = con.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if existing:
            raise ValueError(f"Username '{username}' already exists")
        
        # Insert user
        cursor = con.execute("""
            INSERT INTO users (username, password_hash, email, full_name, role, created_at, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (username, password_hash, email, full_name, role, datetime.utcnow().isoformat(), created_by))
        
        user_id = cursor.lastrowid
    
    return get_user(user_id)


def get_user(identifier: int | str) -> Optional[Dict]:
    """
    Get user by ID or username.
    
    Returns:
        Dict with user info (without password hash) or None if not found
    """
    init_users_table()
    
    with _conn() as con:
        if isinstance(identifier, int):
            row = con.execute("SELECT * FROM users WHERE id = ?", (identifier,)).fetchone()
        else:
            row = con.execute("SELECT * FROM users WHERE username = ?", (identifier,)).fetchone()
        
        if not row:
            return None
        
        return {
            "id": row["id"],
            "username": row["username"],
            "email": row["email"],
            "full_name": row["full_name"],
            "role": row["role"],
            "is_active": bool(row["is_active"]),
            "created_at": row["created_at"],
            "last_login": row["last_login"],
        }


def authenticate_user(username: str, password: str) -> Optional[Dict]:
    """
    Authenticate user with username and password.
    
    Returns:
        User dict if credentials valid, None otherwise
    """
    init_users_table()
    
    with _conn() as con:
        row = con.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        
        if not row:
            return None
        
        if not row["is_active"]:
            return None
        
        # Verify password
        if not auth.verify_password(password, row["password_hash"]):
            return None
        
        # Update last login
        con.execute("UPDATE users SET last_login = ? WHERE id = ?", 
                   (datetime.utcnow().isoformat(), row["id"]))
        
        return {
            "id": row["id"],
            "username": row["username"],
            "email": row["email"],
            "full_name": row["full_name"],
            "role": row["role"],
            "is_active": bool(row["is_active"]),
            "created_at": row["created_at"],
            "last_login": datetime.utcnow().isoformat(),
        }


def list_users(role: Optional[str] = None, include_inactive: bool = False) -> List[Dict]:
    """
    List all users, optionally filtered by role.
    
    Returns:
        List of user dicts (without password hashes)
    """
    init_users_table()
    
    with _conn() as con:
        if role:
            if include_inactive:
                rows = con.execute("SELECT * FROM users WHERE role = ? ORDER BY username", (role,)).fetchall()
            else:
                rows = con.execute("SELECT * FROM users WHERE role = ? AND is_active = 1 ORDER BY username", (role,)).fetchall()
        else:
            if include_inactive:
                rows = con.execute("SELECT * FROM users ORDER BY username").fetchall()
            else:
                rows = con.execute("SELECT * FROM users WHERE is_active = 1 ORDER BY username").fetchall()
        
        return [
            {
                "id": row["id"],
                "username": row["username"],
                "email": row["email"],
                "full_name": row["full_name"],
                "role": row["role"],
                "is_active": bool(row["is_active"]),
                "created_at": row["created_at"],
                "last_login": row["last_login"],
            }
            for row in rows
        ]


def update_user(user_id: int, **fields) -> Dict:
    """
    Update user fields.
    
    Allowed fields: email, full_name, role, is_active
    
    Returns:
        Updated user dict
    
    Raises:
        ValueError: If invalid field or user not found
    """
    allowed_fields = {"email", "full_name", "role", "is_active"}
    updates = {k: v for k, v in fields.items() if k in allowed_fields}
    
    if not updates:
        raise ValueError("No valid fields to update")
    
    init_users_table()
    
    with _conn() as con:
        # Build UPDATE query
        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        values = list(updates.values()) + [user_id]
        
        con.execute(f"UPDATE users SET {set_clause} WHERE id = ?", values)
        
        if con.total_changes == 0:
            raise ValueError(f"User {user_id} not found")
    
    return get_user(user_id)


def change_password(user_id: int, new_password: str) -> bool:
    """
    Change user's password.
    
    Returns:
        True if successful
    
    Raises:
        ValueError: If password invalid or user not found
    """
    # Validate new password
    valid, error = auth.validate_password(new_password)
    if not valid:
        raise ValueError(error)
    
    password_hash = auth.hash_password(new_password)
    
    init_users_table()
    
    with _conn() as con:
        con.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))
        
        if con.total_changes == 0:
            raise ValueError(f"User {user_id} not found")
    
    return True


def delete_user(user_id: int) -> bool:
    """
    Delete a user (permanently).
    
    For safety, consider using update_user(user_id, is_active=False) instead.
    
    Returns:
        True if deleted
    """
    init_users_table()
    
    with _conn() as con:
        con.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return con.total_changes > 0


def deactivate_user(user_id: int) -> Dict:
    """Deactivate a user (soft delete)."""
    return update_user(user_id, is_active=False)


def activate_user(user_id: int) -> Dict:
    """Reactivate a user."""
    return update_user(user_id, is_active=True)


def get_user_count() -> Dict[str, int]:
    """Get count of users by role."""
    init_users_table()
    
    with _conn() as con:
        total = con.execute("SELECT COUNT(*) FROM users WHERE is_active = 1").fetchone()[0]
        admins = con.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1").fetchone()[0]
        faculty = con.execute("SELECT COUNT(*) FROM users WHERE role = 'faculty' AND is_active = 1").fetchone()[0]
        students = con.execute("SELECT COUNT(*) FROM users WHERE role = 'student' AND is_active = 1").fetchone()[0]
        
        return {
            "total": total,
            "admins": admins,
            "faculty": faculty,
            "students": students,
        }