"""Fail closed when a cloud deployment lacks durable storage or private setup."""
import base64
import hashlib
import os
from urllib.parse import urlsplit


def configure():
    database = os.getenv("DATABASE_URL", "")
    if not database.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
        raise ValueError("Configura DATABASE_URL con el Session pooler de Supabase; no se admite SQLite en Render.")
    origin = os.getenv("APP_ORIGIN") or os.getenv("RENDER_EXTERNAL_URL", "")
    parsed = urlsplit(origin)
    if parsed.scheme != "https" or not parsed.hostname or parsed.path not in {"", "/"} or parsed.query or parsed.fragment or parsed.username:
        raise ValueError("Configura APP_ORIGIN con la dirección HTTPS de Render.")
    master = os.getenv("PABLO_CLOUD_MASTER_KEY", "")
    if len(master) < 32:
        raise ValueError("Falta PABLO_CLOUD_MASTER_KEY: usa el secreto generado por Render y conserva una copia.")
    if len(os.getenv("PABLO_OWNER_PASSWORD", "")) < 12:
        raise ValueError("Configura una contraseña privada de al menos 12 caracteres en PABLO_OWNER_PASSWORD.")
    os.environ.update(PABLO_CLOUD="true", COOKIE_SECURE="true", APP_ORIGIN=origin.rstrip("/"),
                      PABLO_SECRET_KEY=base64.urlsafe_b64encode(hashlib.sha256(master.encode()).digest()).decode())
