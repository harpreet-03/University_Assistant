"""
auth.py — Authentication & Authorization for EduVerse AI

Features:
- Password hashing with bcrypt
- JWT token generation and verification
- Role-based access control decorators
- Session management
"""

import os
import bcrypt
import secrets
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional, Dict

from jose import JWTError, jwt
from fastapi import HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Load from environment or use defaults
JWT_SECRET = os.getenv("JWT_SECRET", secrets.token_urlsafe(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_DAYS = int(os.getenv("JWT_EXPIRY_DAYS", "7"))

security = HTTPBearer(auto_error=False)


# ═══════════════════════════════════════════════════════════════
#  Password Hashing (bcrypt)
# ═══════════════════════════════════════════════════════════════

def hash_password(password: str) -> str:
    """Hash a password using bcrypt with salt."""
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash."""
    try:
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════
#  JWT Token Management
# ═══════════════════════════════════════════════════════════════

def create_jwt(user_id: int, username: str, role: str, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT token for a user.
    
    Token payload:
        sub: user_id
        username: username
        role: role (admin/faculty/student)
        exp: expiration timestamp
        jti: unique token ID (for revocation)
    """
    if expires_delta is None:
        expires_delta = timedelta(days=JWT_EXPIRY_DAYS)
    
    expire = datetime.utcnow() + expires_delta
    jti = secrets.token_urlsafe(16)
    
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "exp": expire,
        "jti": jti,
        "iat": datetime.utcnow(),
    }
    
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token


def verify_jwt(token: str) -> Optional[Dict]:
    """
    Verify and decode a JWT token.
    
    Returns:
        Dict with user info if valid, None if invalid/expired
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        
        # Check expiration
        exp = payload.get("exp")
        if exp and datetime.utcnow() > datetime.fromtimestamp(exp):
            return None
        
        return {
            "user_id": int(payload.get("sub")),
            "username": payload.get("username"),
            "role": payload.get("role"),
            "jti": payload.get("jti"),
        }
    except JWTError:
        return None


# ═══════════════════════════════════════════════════════════════
#  Authentication Dependency (FastAPI)
# ═══════════════════════════════════════════════════════════════

async def get_current_user(request: Request, credentials: Optional[HTTPAuthorizationCredentials] = None) -> Optional[Dict]:
    """
    Extract and verify JWT from Authorization header.
    Used as a FastAPI dependency.
    """
    if not credentials:
        # Try to get from header manually
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None
        token = auth_header.replace("Bearer ", "")
    else:
        token = credentials.credentials
    
    user_data = verify_jwt(token)
    if not user_data:
        return None
    
    return user_data


def require_auth(allowed_roles: list = None):
    """
    Decorator to protect routes with authentication and role-based access.
    
    Usage:
        @app.get("/admin/users")
        @require_auth(["admin"])
        async def list_users():
            ...
    
    Args:
        allowed_roles: List of roles that can access (e.g., ["admin", "faculty"])
                      If None, any authenticated user can access
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            # Extract token
            auth_header = request.headers.get("Authorization")
            if not auth_header or not auth_header.startswith("Bearer "):
                raise HTTPException(401, detail="Authentication required")
            
            token = auth_header.replace("Bearer ", "")
            user_data = verify_jwt(token)
            
            if not user_data:
                raise HTTPException(401, detail="Invalid or expired token")
            
            # Check role if specified
            if allowed_roles and user_data["role"] not in allowed_roles:
                raise HTTPException(403, detail=f"Access denied. Required role: {', '.join(allowed_roles)}")
            
            # Add user data to request state for use in route
            request.state.user = user_data
            
            return await func(request, *args, **kwargs)
        return wrapper
    return decorator


# ═══════════════════════════════════════════════════════════════
#  Password Validation
# ═══════════════════════════════════════════════════════════════

def validate_password(password: str) -> tuple[bool, str]:
    """
    Validate password strength.
    
    Requirements:
        - At least 8 characters
        - Contains at least one number
        - Contains at least one letter
    
    Returns:
        (is_valid, error_message)
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    
    if not any(c.isdigit() for c in password):
        return False, "Password must contain at least one number"
    
    if not any(c.isalpha() for c in password):
        return False, "Password must contain at least one letter"
    
    return True, ""


# ═══════════════════════════════════════════════════════════════
#  Username Validation
# ═══════════════════════════════════════════════════════════════

def validate_username(username: str) -> tuple[bool, str]:
    """
    Validate username format.
    
    Requirements:
        - 3-30 characters
        - Alphanumeric + underscore/dot only
        - Must start with letter
    
    Returns:
        (is_valid, error_message)
    """
    if len(username) < 3 or len(username) > 30:
        return False, "Username must be 3-30 characters"
    
    if not username[0].isalpha():
        return False, "Username must start with a letter"
    
    if not all(c.isalnum() or c in ('_', '.') for c in username):
        return False, "Username can only contain letters, numbers, underscore, and dot"
    
    return True, ""