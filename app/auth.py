import hashlib
import os
from fastapi import Depends, Request, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db


SESSION_COOKIE = "bp_session"


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    return hash_password(password) == hashed


def create_session_value(password: str) -> str:
    """Simple HMAC-signed session value using SECRET_KEY."""
    from itsdangerous import URLSafeSerializer
    secret = os.environ.get("SECRET_KEY", "dev-secret")
    s = URLSafeSerializer(secret)
    return s.dumps({"auth": True})


def validate_session_value(value: str) -> bool:
    from itsdangerous import URLSafeSerializer, BadSignature
    secret = os.environ.get("SECRET_KEY", "dev-secret")
    s = URLSafeSerializer(secret)
    try:
        data = s.loads(value)
        return data.get("auth") is True
    except BadSignature:
        return False


def require_auth(request: Request):
    """FastAPI dependency — raises 302 redirect to /login if not authenticated."""
    session_val = request.cookies.get(SESSION_COOKIE)
    if not session_val or not validate_session_value(session_val):
        raise HTTPException(status_code=302, headers={"Location": "/login"})
