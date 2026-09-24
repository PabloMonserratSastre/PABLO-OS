import hashlib
import hmac
import os
import secrets
import time
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from sqlalchemy import delete, select

from .db import DB, Session


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(value: str) -> str:
    salt = secrets.token_hex(16)
    key = hashlib.scrypt(value.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
    return f"{salt}:{key}"


def verify(value: str, stored: str) -> bool:
    salt, key = stored.split(":")
    actual = hashlib.scrypt(value.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
    return hmac.compare_digest(actual, key)


def new_session(db, response):
    token = secrets.token_urlsafe(32)
    db.execute(delete(Session).where(Session.expires < int(time.time())))
    db.add(Session(id=digest(token), expires=int(time.time()) + 86400))
    db.commit()
    response.set_cookie(
        "pablo_session",
        token,
        httponly=True,
        samesite="strict",
        secure=os.getenv("COOKIE_SECURE", "false") == "true",
        max_age=86400,
        path="/",
    )


def require_user(request: Request):
    token = request.cookies.get("pablo_session", "")
    with DB() as db:
        session = db.scalar(select(Session).where(Session.id == digest(token)))
        if not session or session.expires < int(time.time()):
            raise HTTPException(401, "Inicia sesión para continuar.")
    return 1


def allowed_origin(origin: str, configured: str) -> bool:
    """Allow only the configured origin and equivalent literal loopback hosts."""

    def parse(value):
        try:
            url = urlsplit(value.strip())
            if (
                url.scheme not in {"http", "https"}
                or not url.hostname
                or url.username is not None
                or url.password is not None
                or url.path not in {"", "/"}
                or url.query
                or url.fragment
            ):
                return None
            return url.scheme, url.hostname, url.port or (443 if url.scheme == "https" else 80)
        except ValueError:
            return None

    actual, expected = parse(origin), parse(configured)
    if actual is None or expected is None:
        return False
    if actual == expected:
        return True
    loopback = {"localhost", "127.0.0.1", "::1"}
    return (
        actual[0] == expected[0]
        and actual[2] == expected[2]
        and actual[1] in loopback
        and expected[1] in loopback
    )
