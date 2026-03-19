"""
audit.py — Audit Logging for EduVerse AI

Tracks all user actions for security and compliance.
"""

import sqlite3
from datetime import datetime
from typing import Optional, List, Dict
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "db" / "structured.db"


def _conn():
    """Get database connection with row factory."""
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    return con


def log_action(user_id: Optional[int], action: str, resource: str = None, ip_address: str = None):
    """
    Log a user action.
    
    Args:
        user_id: ID of user performing action (None for system actions)
        action: Action type (e.g., 'login', 'upload', 'delete', 'logout')
        resource: Resource affected (e.g., filename, user_id)
        ip_address: Client IP address
    
    Examples:
        log_action(1, 'login', ip_address='192.168.1.1')
        log_action(1, 'upload', 'Academic_rules.pdf', '192.168.1.1')
        log_action(1, 'delete', 'old_file.pdf', '192.168.1.1')
        log_action(1, 'create_user', 'john_doe', '192.168.1.1')
    """
    with _conn() as con:
        con.execute("""
            INSERT INTO audit_log (user_id, action, resource, ip_address, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, action, resource, ip_address, datetime.utcnow().isoformat()))


def get_audit_logs(user_id: Optional[int] = None, action: Optional[str] = None, 
                   limit: int = 100, offset: int = 0) -> List[Dict]:
    """
    Retrieve audit logs with optional filtering.
    
    Args:
        user_id: Filter by user ID
        action: Filter by action type
        limit: Maximum number of records to return
        offset: Number of records to skip (for pagination)
    
    Returns:
        List of audit log entries with user information
    """
    with _conn() as con:
        # Build query
        query = """
            SELECT 
                audit_log.*,
                users.username,
                users.full_name,
                users.role
            FROM audit_log
            LEFT JOIN users ON audit_log.user_id = users.id
            WHERE 1=1
        """
        params = []
        
        if user_id is not None:
            query += " AND audit_log.user_id = ?"
            params.append(user_id)
        
        if action:
            query += " AND audit_log.action = ?"
            params.append(action)
        
        query += " ORDER BY audit_log.timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        rows = con.execute(query, params).fetchall()
        
        return [
            {
                "id": row["id"],
                "user_id": row["user_id"],
                "username": row["username"] or "System",
                "full_name": row["full_name"],
                "role": row["role"],
                "action": row["action"],
                "resource": row["resource"],
                "ip_address": row["ip_address"],
                "timestamp": row["timestamp"],
            }
            for row in rows
        ]


def get_user_activity(user_id: int, limit: int = 50) -> List[Dict]:
    """Get recent activity for a specific user."""
    return get_audit_logs(user_id=user_id, limit=limit)


def get_recent_logins(limit: int = 20) -> List[Dict]:
    """Get recent login events."""
    return get_audit_logs(action='login', limit=limit)


def get_upload_history(limit: int = 50) -> List[Dict]:
    """Get recent file upload events."""
    return get_audit_logs(action='upload', limit=limit)


def get_delete_history(limit: int = 50) -> List[Dict]:
    """Get recent file deletion events."""
    return get_audit_logs(action='delete', limit=limit)


def get_audit_summary() -> Dict:
    """
    Get summary statistics for audit logs.
    
    Returns:
        Dict with counts by action type
    """
    with _conn() as con:
        # Total actions in last 24 hours
        day_ago = (datetime.utcnow() - timedelta(hours=24)).isoformat()
        total_24h = con.execute(
            "SELECT COUNT(*) FROM audit_log WHERE timestamp > ?", (day_ago,)
        ).fetchone()[0]
        
        # Total actions in last 7 days
        week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
        total_7d = con.execute(
            "SELECT COUNT(*) FROM audit_log WHERE timestamp > ?", (week_ago,)
        ).fetchone()[0]
        
        # Count by action type (all time)
        action_counts = {}
        rows = con.execute("""
            SELECT action, COUNT(*) as count 
            FROM audit_log 
            GROUP BY action 
            ORDER BY count DESC
        """).fetchall()
        
        for row in rows:
            action_counts[row["action"]] = row["count"]
        
        # Most active users (last 7 days)
        active_users = []
        rows = con.execute("""
            SELECT 
                audit_log.user_id,
                users.username,
                users.full_name,
                COUNT(*) as action_count
            FROM audit_log
            LEFT JOIN users ON audit_log.user_id = users.id
            WHERE audit_log.timestamp > ?
            GROUP BY audit_log.user_id
            ORDER BY action_count DESC
            LIMIT 5
        """, (week_ago,)).fetchall()
        
        for row in rows:
            if row["user_id"]:
                active_users.append({
                    "user_id": row["user_id"],
                    "username": row["username"],
                    "full_name": row["full_name"],
                    "action_count": row["action_count"],
                })
        
        return {
            "total_24h": total_24h,
            "total_7d": total_7d,
            "action_counts": action_counts,
            "most_active_users": active_users,
        }


# Import timedelta for summary function
from datetime import timedelta