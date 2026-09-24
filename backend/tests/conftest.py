import os
import tempfile
from cryptography.fernet import Fernet

# Tests must never depend on or modify the real Windows credential vault.
os.environ["PABLO_SECRET_KEY"] = Fernet.generate_key().decode()

os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")
os.environ.pop("AI_API_KEY", None)
os.environ.pop("AI_EMBED_MODEL", None)

import pytest
from alembic import command as migration
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import delete

from pablo.db import Base, engine
from pablo.main import app, attempts

migration.upgrade(Config("backend/alembic.ini"), "head")

@pytest.fixture
def client():
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(delete(table))
    attempts.clear()
    with TestClient(app) as c:
        c.headers["X-Pablo-Request"] = "1"
        result = c.post(
            "/api/v1/auth/setup", json={"name": "Pablo test", "password": "Temporary-test-pass-2026"}
        )
        assert result.status_code == 200
        yield c

