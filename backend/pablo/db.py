"""Durable state shared by API and worker. PostgreSQL in Compose; SQLite for offline tests."""

import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Float, Integer, LargeBinary, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def uid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Owner(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    password: Mapped[str] = mapped_column(Text)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires: Mapped[int] = mapped_column(Integer)


class Item(Base):
    """Versioned domain records; kind is allowlisted and payload validated at the API."""

    __tablename__ = "items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(30), index=True)
    title: Mapped[str] = mapped_column(String(300))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String(40), default=now)
    updated_at: Mapped[str] = mapped_column(String(40), default=now)
    version: Mapped[int] = mapped_column(Integer, default=1)


class Run(Base):
    __tablename__ = "agent_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    goal: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), default="QUEUED", index=True)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    conversation_id: Mapped[str] = mapped_column(String(36))
    plan: Mapped[list] = mapped_column(JSON, default=list)
    result: Mapped[str] = mapped_column(Text, default="")
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String(40), default=now)
    updated_at: Mapped[str] = mapped_column(String(40), default=now)

    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[float | None] = mapped_column(Float, nullable=True)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    tool: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    created_at: Mapped[str] = mapped_column(String(40), default=now)
    decided_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class Audit(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    run_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String(40), default=now)


class Chunk(Base):
    __tablename__ = "document_chunks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    document_id: Mapped[str] = mapped_column(String(36), index=True)
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)


url = os.getenv("DATABASE_URL", "sqlite:///./pablo.db")
if url.startswith(("postgres://", "postgresql://")):
    url = "postgresql+psycopg://" + url.split("://", 1)[1]
connection_options = {"check_same_thread": False} if url.startswith("sqlite") else {}
if os.getenv("PABLO_CLOUD") == "true":
    connection_options = {"options": "-csearch_path=pablo", "connect_timeout": 15, "sslmode": "require"}
engine = create_engine(
    url, pool_pre_ping=True, connect_args=connection_options
)
if url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def sqlite_config(conn, _):
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")


DB = sessionmaker(engine, expire_on_commit=False)


def audit(db, action: str, status: str = "OK", run_id: str | None = None, **detail):
    # Only operational metadata, never tool payloads, document text or credentials.
    db.add(Audit(action=action, status=status, run_id=run_id, detail=detail))


class Schedule(Base):
    __tablename__ = "schedules"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(String(300))
    goal: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(20), default="ASK")
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    next_run: Mapped[str] = mapped_column(String(40), index=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), default=now)


class Runtime(Base):
    __tablename__ = "runtime_status"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    updated_at: Mapped[str] = mapped_column(String(40), default=now)


class ServiceConfig(Base):
    __tablename__ = "service_config"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    encrypted: Mapped[str] = mapped_column(Text, default="")


class BudgetPeriod(Base):
    __tablename__ = "budget_periods"
    id: Mapped[str] = mapped_column(String(7), primary_key=True)
    committed_micro: Mapped[int] = mapped_column(Integer, default=0)
    actual_micro: Mapped[int] = mapped_column(Integer, default=0)


class WorkspaceFile(Base):
    __tablename__ = "workspace_files"
    path: Mapped[str] = mapped_column(String(500), primary_key=True)
    content: Mapped[bytes] = mapped_column(LargeBinary)
    checksum: Mapped[str] = mapped_column(String(64))
