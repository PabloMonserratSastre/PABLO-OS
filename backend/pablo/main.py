import asyncio
import json
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import IntegrityError

from .capabilities import router as capabilities_router
from .db import (
    DB,
    Approval,
    Audit,
    Chunk,
    Item,
    Owner,
    Run,
    Runtime,
    Schedule,
    Session,
    audit,
    engine,
    now,
)
from .integrations import router as integrations_router
from .knowledge import extract_isolated, index, prepare_vectors, search
from .pulse import build_pulse
from .scheduling import create_execution, parse_instant
from .schemas import Command, Credentials, Decision, Enabled, Record, ScheduledCommand, Settings
from .security import allowed_origin, digest, new_session, password_hash, require_user, verify
from .tools import AGENTS, registry
from .worker import TERMINAL

app = FastAPI(title="PABLO OS", version="0.4.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
attempts = defaultdict(deque)
AUTH_WINDOW_SECONDS = 300
AUTH_FAILURE_LIMIT = 8
KIND = {"projects", "tasks", "memory", "documents", "artifacts", "conversations", "messages", "workflows"}
EDITABLE = {"projects", "tasks", "memory", "workflows"}


def item_json(item):
    return {
        "id": item.id,
        "kind": item.kind,
        "title": item.title,
        **item.data,
        "created_at": item.created_at,
        "version": item.version,
    }


def run_json(run):
    return {
        key: getattr(run, key)
        for key in [
            "id",
            "goal",
            "mode",
            "status",
            "project_id",
            "conversation_id",
            "plan",
            "result",
            "usage",
            "created_at",
            "updated_at",
        ]
    }


def get_item(db, item_id, kind=None):
    row = db.get(Item, item_id)
    if not row or (kind and row.kind != kind):
        raise HTTPException(404, "Elemento no encontrado.")
    return row


@app.middleware("http")
async def safeguards(request: Request, call_next):
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        # JSON endpoints require custom same-origin header; forms cannot forge it.
        if request.headers.get("x-pablo-request") != "1":
            return Response("Petición no autorizada", status_code=403)
        origin = request.headers.get("origin")
        expected = os.getenv("APP_ORIGIN", "http://localhost:8000")
        if origin and not allowed_origin(origin, expected):
            return Response("Origen no autorizado", status_code=403)
        limit = 52_500_000 if request.url.path == "/api/v1/import" else 5_500_000
        try:
            if int(request.headers.get("content-length", "0")) > limit:
                return Response("Archivo demasiado grande", status_code=413)
        except ValueError:
            return Response(status_code=400)
        buffered = bytearray()
        async for chunk in request.stream():
            buffered.extend(chunk)
            if len(buffered) > limit:
                return Response("Petición demasiado grande", status_code=413)
        request._body = bytes(buffered)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Content-Security-Policy", (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
    ))
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(ValueError)
async def invalid_value(request, exc):
    from fastapi.responses import JSONResponse

    return JSONResponse({"detail": str(exc)[:500]}, status_code=422)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    with DB() as db:
        db.execute(text("SELECT 1"))
    return {
        "database": "ready",
        "dialect": engine.dialect.name,
        "application": "pablo-os",
        "version": "0.4.0",
        "installation": os.getenv("PABLO_INSTALLATION_ID", ""),
    }


@app.get("/api/v1/auth/status")
def auth_status():
    with DB() as db:
        return {"setup_required": db.get(Owner, 1) is None}


@app.post("/api/v1/auth/setup")
def setup(body: Credentials, response: Response):
    if os.getenv("PABLO_CLOUD") == "true":
        raise HTTPException(403, "La cuenta se prepara de forma privada al desplegar el servidor.")
    with DB() as db:
        if db.get(Owner, 1):
            raise HTTPException(409, "La cuenta local ya existe.")
        db.add(
            Owner(
                id=1,
                name=body.name,
                password=password_hash(body.password),
                settings=Settings(name=body.name).model_dump(),
            )
        )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "La cuenta local ya existe.")
        new_session(db, response)
    return {"ok": True}


@app.post("/api/v1/auth/login")
def login(body: Credentials, response: Response, request: Request):
    key = request.client.host if request.client else "local"
    failures = attempts[key]
    cutoff = time.time() - AUTH_WINDOW_SECONDS
    while failures and failures[0] < cutoff:
        failures.popleft()
    if len(failures) >= AUTH_FAILURE_LIMIT:
        raise HTTPException(429, "Demasiados intentos fallidos. Espera cinco minutos.")
    with DB() as db:
        owner = db.get(Owner, 1)
        if not owner or not verify(body.password, owner.password):
            failures.append(time.time())
            raise HTTPException(401, "Contraseña incorrecta.")
        attempts.pop(key, None)
        new_session(db, response)
    return {"ok": True}


@app.post("/api/v1/auth/logout", dependencies=[Depends(require_user)])
def logout(request: Request, response: Response):
    with DB() as db:
        db.execute(delete(Session).where(Session.id == digest(request.cookies.get("pablo_session", ""))))
        db.commit()
    response.delete_cookie("pablo_session")
    return {"ok": True}


@app.get("/api/v1/state", dependencies=[Depends(require_user)])
def state():
    from .configuration import provider_config

    with DB() as db:
        config = provider_config(db)
        owner = db.get(Owner, 1)
        rows = db.scalars(
            select(Item).where(Item.kind != "messages").order_by(Item.created_at.desc()).limit(5001)
        ).all()
        truncated = len(rows) > 5000
        rows = rows[:5000] + list(
            db.scalars(
                select(Item).where(Item.kind == "messages").order_by(Item.created_at.desc()).limit(200)
            )
        )
        active_runs = list(db.scalars(select(Run).where(Run.status.not_in(list(TERMINAL)))))
        recent_runs = list(db.scalars(select(Run).order_by(Run.created_at.desc()).limit(40)))
        visible_runs = sorted(
            {r.id: r for r in active_runs + recent_runs}.values(), key=lambda r: r.created_at, reverse=True
        )
        serialized_items = [item_json(r) for r in rows]
        serialized_runs = [run_json(r) for r in visible_runs]
        pending_approvals = [
            {"id": a.id, "run_id": a.run_id, "tool": a.tool, "payload": a.payload, "status": a.status}
            for a in db.scalars(select(Approval).where(Approval.status == "PENDING"))
        ]
        return {
            "truncated": truncated,
            "daily_summary": (lambda r: run_json(r) if r else None)(db.scalar(select(Run).where(Run.goal == "Preparar mi resumen diario").order_by(Run.created_at.desc()).limit(1))),
            "profile": owner.settings | {"name": owner.name},
            "items": serialized_items,
            "runs": serialized_runs,
            "approvals": pending_approvals,
            "pulse": build_pulse(
                serialized_items,
                serialized_runs,
                len(pending_approvals),
                owner.settings.get("timezone", "Europe/Madrid"),
                owner.name,
            ),
            "ai": {
                "configured": bool(config["api_key"] and config["model"]),
                "model": config["model"],
                "embeddings": bool(config["embed_model"]),
            },
        }


def validate_record(db, body, kind, item_id=None):
    if body.project_id:
        get_item(db, body.project_id, "projects")
    if kind == "memory":
        settings = db.get(Owner, 1).settings
        if not settings.get("memory_enabled", True) or body.category not in settings.get(
            "memory_categories", []
        ):
            raise HTTPException(403, "Este tipo de memoria está desactivado.")
    if kind == "tasks":
        if body.status not in {
            "TODO",
            "PLANNED",
            "IN_PROGRESS",
            "WAITING_APPROVAL",
            "BLOCKED",
            "TESTING",
            "DONE",
            "FAILED",
            "CANCELLED",
        }:
            raise ValueError("Estado de tarea no válido.")

        def visit(dep, seen):
            if dep == item_id or dep in seen:
                raise ValueError("Dependencias cíclicas.")
            task = get_item(db, dep, "tasks")
            for child in task.data.get("dependencies", []):
                visit(child, seen | {dep})

        for dep in body.dependencies:
            visit(dep, set())
        if body.status == "DONE" and any(
            get_item(db, dep, "tasks").data.get("status") != "DONE" for dep in body.dependencies
        ):
            raise ValueError("Completa primero las dependencias.")
    if kind == "projects" and body.status not in {
        "IDEA",
        "PLANNING",
        "ACTIVE",
        "BLOCKED",
        "REVIEW",
        "COMPLETED",
        "ARCHIVED",
    }:
        raise ValueError("Estado de proyecto no válido.")
    if body.due:
        from datetime import date

        date.fromisoformat(body.due)


@app.post("/api/v1/items/{kind}", dependencies=[Depends(require_user)])
def create(kind: str, body: Record):
    if kind not in EDITABLE:
        raise HTTPException(404)
    with DB() as db:
        validate_record(db, body, kind)
        item = Item(kind=kind, title=body.title, data=body.model_dump(exclude={"title", "version"}))
        db.add(item)
        audit(db, f"{kind}.created")
        db.commit()
        return item_json(item)


@app.put("/api/v1/items/{item_id}", dependencies=[Depends(require_user)])
def edit(item_id: str, body: Record):
    with DB() as db:
        item = get_item(db, item_id)
        if item.kind not in EDITABLE:
            raise HTTPException(403)
        validate_record(db, body, item.kind, item_id)
        version = body.version
        result = db.execute(
            update(Item)
            .where(Item.id == item_id, Item.version == version)
            .values(
                title=body.title,
                data=body.model_dump(exclude={"title", "version"}),
                version=Item.version + 1,
                updated_at=now(),
            )
        )
        if not result.rowcount:
            raise HTTPException(409, "El elemento cambió. Actualiza la página antes de guardar.")
        audit(db, f"{item.kind}.updated")
        db.commit()
        db.refresh(item)
        return item_json(item)


@app.delete("/api/v1/items/{item_id}", dependencies=[Depends(require_user)])
def remove(item_id: str):
    with DB() as db:
        item = get_item(db, item_id)
        if item.kind not in EDITABLE | {"documents", "artifacts", "conversations"}:
            raise HTTPException(403)
        if item.kind == "conversations":
            runs = db.scalars(select(Run).where(Run.conversation_id == item.id)).all()
            if any(r.status not in TERMINAL or (r.lease_until and r.lease_until > time.time()) for r in runs):
                raise HTTPException(
                    409, "Detén las ejecuciones activas y espera a que terminen antes de borrar el historial."
                )
            ids = [r.id for r in runs]
            db.execute(delete(Approval).where(Approval.run_id.in_(ids)))
            db.execute(delete(Audit).where(Audit.run_id.in_(ids)))
            db.execute(
                delete(Item).where(
                    Item.kind == "messages", Item.data["conversation_id"].as_string() == item.id
                )
            )
            db.execute(delete(Run).where(Run.conversation_id == item.id))
        if item.kind == "projects":
            from .project_lifecycle import detach_project
            try:
                detach_project(db, item.id)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from None
        if item.kind == "tasks":
            for child in db.scalars(select(Item).where(Item.kind == "tasks")):
                if item.id in child.data.get("dependencies", []):
                    raise HTTPException(409, "Otra tarea depende de esta. Elimina primero la dependencia.")
        db.execute(delete(Chunk).where(Chunk.document_id == item_id))
        db.delete(item)
        audit(db, "item.deleted")
        db.commit()
    return {"deleted": True}


@app.put("/api/v1/settings", dependencies=[Depends(require_user)])
def settings(body: Settings):
    try:
        ZoneInfo(body.timezone)
    except ZoneInfoNotFoundError:
        raise ValueError("Zona horaria no válida.")
    with DB() as db:
        owner = db.get(Owner, 1)
        owner.name, owner.settings = body.name, body.model_dump()
        audit(db, "settings.updated")
        db.commit()
    return body


@app.post("/api/v1/commands", dependencies=[Depends(require_user)])
def command(body: Command):
    with DB() as db:
        active = db.scalars(
            select(Run).where(Run.status.in_(["QUEUED", "RUNNING", "WAITING_APPROVAL"]))
        ).all()
        if len(active) >= 20:
            raise HTTPException(429, "Termina o cancela alguna ejecución antes de continuar.")
        if body.project_id:
            get_item(db, body.project_id, "projects")
        if body.conversation_id:
            conversation = get_item(db, body.conversation_id, "conversations")
            if body.project_id is None:
                body.project_id = conversation.data.get("project_id")
        run = create_execution(db, body)
        db.commit()
        return run_json(run)


@app.post("/api/v1/runs/{run_id}/cancel", dependencies=[Depends(require_user)])
def cancel(run_id: str):
    with DB() as db:
        run = db.get(Run, run_id)
        if not run:
            raise HTTPException(404)
        if run.status in TERMINAL:
            raise HTTPException(409, "La ejecución ya terminó.")
        run.status = "CANCELLED"
        db.execute(
            update(Approval)
            .where(Approval.run_id == run_id, Approval.status == "PENDING")
            .values(status="REJECTED", decided_at=now())
        )
        audit(db, "execution.cancelled", run_id=run_id)
        db.commit()
    return {"status": "CANCELLED"}


@app.post("/api/v1/runs/{run_id}/retry", dependencies=[Depends(require_user)])
def retry(run_id: str):
    with DB() as db:
        run = db.get(Run, run_id)
        if not run or run.status != "FAILED":
            raise HTTPException(409, "Solo pueden reintentarse ejecuciones fallidas.")
        if any(step.get("status") == "EXECUTING" for step in run.plan):
            raise HTTPException(409, "Una acción puede haberse realizado antes del fallo. Comprueba su resultado; no se reintentará automáticamente.")
        attempts_count = run.usage.get("retries", 0)
        if attempts_count >= 2:
            raise HTTPException(409, "Se alcanzó el límite de dos reintentos.")
        run.usage = run.usage | {"retries": attempts_count + 1}
        run.status = "RUNNING" if run.plan else "QUEUED"
        audit(db, "execution.retried", run_id=run_id)
        db.commit()
    return {"status": run.status}


@app.post("/api/v1/approvals/{approval_id}", dependencies=[Depends(require_user)])
def decide(approval_id: str, body: Decision):
    with DB() as db:
        approval = db.get(Approval, approval_id)
        if not approval or approval.status != "PENDING":
            raise HTTPException(409, "Esta aprobación ya se resolvió.")
        run = db.get(Run, approval.run_id)
        if run.status != "WAITING_APPROVAL":
            raise HTTPException(409, "La ejecución ya no espera aprobación.")
        result = db.execute(
            update(Approval)
            .where(Approval.id == approval.id, Approval.status == "PENDING")
            .values(status="APPROVED" if body.approve else "REJECTED", decided_at=now())
        )
        if not result.rowcount:
            raise HTTPException(409)
        run.status = "RUNNING" if body.approve else "CANCELLED"
        audit(db, "approval.decided", "APPROVED" if body.approve else "REJECTED", run.id)
        db.commit()
    return {"ok": True}


@app.get("/api/v1/runs/{run_id}/events", dependencies=[Depends(require_user)])
async def events(run_id: str):
    async def stream():
        previous = ""
        for _ in range(300):
            with DB() as db:
                run = db.get(Run, run_id)
                if not run:
                    return
                payload = json.dumps(run_json(run), ensure_ascii=False)
                status = run.status
            if payload != previous:
                yield f"data: {payload}\n\n"
                previous = payload
            else:
                yield ": keepalive\n\n"
            if status in TERMINAL or status == "WAITING_APPROVAL":
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


@app.post("/api/v1/documents", dependencies=[Depends(require_user)])
def upload(project_id: str | None = None, file: UploadFile = File(...)):
    data = file.file.read(5_000_001)
    if len(data) > 5_000_000:
        raise HTTPException(413, "Máximo 5 MB por archivo.")
    try:
        content = extract_isolated(file.filename or "archivo.txt", data)
    except ValueError:
        raise
    except Exception:
        raise ValueError("No se pudo extraer texto de este archivo. Comprueba que no esté dañado ni cifrado.")
    vectors = prepare_vectors(content)
    with DB() as db:
        if project_id:
            get_item(db, project_id, "projects")
        doc = Item(
            kind="documents",
            title=Path(file.filename or "archivo").name[:300],
            data={
                "project_id": project_id,
                "bytes": len(data),
                "description": content[:500],
                "status": "INDEXED",
            },
        )
        db.add(doc)
        db.flush()
        count = index(db, doc.id, content, vectors=vectors)
        doc.data = doc.data | {"chunks": count}
        audit(db, "document.indexed", chunks=count)
        db.commit()
        return item_json(doc)


@app.get("/api/v1/search", dependencies=[Depends(require_user)])
def global_search(q: str = "", project_id: str | None = None):
    if len(q) > 500:
        raise ValueError("Búsqueda demasiado larga.")
    with DB() as db:
        items = db.scalars(
            select(Item).where(Item.title.ilike("%" + q.replace("%", "").replace("_", "") + "%")).limit(30)
        ).all()
        return {
            "items": [item_json(r) for r in items],
            "sources": search(db, q, project_id) if q.strip() else [],
        }


@app.get("/api/v1/agents", dependencies=[Depends(require_user)])
def agents():
    return [
        {
            "name": name,
            "description": description,
            "tools": [t["id"] for t in registry.list() if t["agent"] == name],
            "status": "AVAILABLE" if any(t["agent"] == name for t in registry.list()) else "ADAPTER_PENDING",
        }
        for name, description in AGENTS
    ]


@app.get("/api/v1/integrations", dependencies=[Depends(require_user)])
def integrations():
    from .configuration import public_provider
    from .integrations import integration_status

    with DB() as db:
        provider = public_provider(db)
        return integration_status(db) + [
            {"name": "Proveedor IA", "status": "CONFIGURED" if provider["configured"] else "DISCONNECTED",
             "detail": "Configura tu proveedor y presupuesto en Ajustes."},
            {"name": "Workspace local", "status": "AVAILABLE", "detail": "Archivos, prototipos, Git y ejecución de código revisado con aprobación."},
            {"name": "Documentos", "status": "CONNECTED", "detail": "Extracción, búsqueda y reindexación locales; embeddings opcionales."},
        ]


@app.get("/api/v1/activity", dependencies=[Depends(require_user)])
def activity():
    with DB() as db:
        return [
            {
                "id": r.id,
                "action": r.action,
                "status": r.status,
                "detail": r.detail,
                "created_at": r.created_at,
                "run_id": r.run_id,
            }
            for r in db.scalars(select(Audit).order_by(Audit.created_at.desc()).limit(150))
        ]


@app.get("/api/v1/export", dependencies=[Depends(require_user)])
def export():
    with DB() as db:
        result = {
            "schema_version": 3,
            "schedules": [schedule_json(row) for row in db.scalars(select(Schedule))],
            "exported_at": now(),
            "settings": db.get(Owner, 1).settings,
            "items": [item_json(r) for r in db.scalars(select(Item))],
            "runs": [run_json(r) for r in db.scalars(select(Run))],
            "document_chunks": [
                {"document_id": c.document_id, "position": c.position, "text": c.text}
                for c in db.scalars(select(Chunk))
            ],
        }
    return Response(
        json.dumps(result, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="pablo-os-export.json"'},
    )


def schedule_json(row):
    return {
        key: getattr(row, key)
        for key in [
            "id",
            "title",
            "goal",
            "mode",
            "project_id",
            "next_run",
            "interval_minutes",
            "enabled",
            "last_run_id",
            "created_at",
        ]
    }


@app.get("/api/v1/runs/{run_id}", dependencies=[Depends(require_user)])
def get_run(run_id: str):
    with DB() as db:
        row = db.get(Run, run_id)
        if not row:
            raise HTTPException(404, "Ejecución no encontrada.")
        return run_json(row)


@app.get("/api/v1/runtime", dependencies=[Depends(require_user)])
def runtime():
    with DB() as db:
        heartbeat = db.get(Runtime, "worker")
        age = (
            (datetime.now(timezone.utc) - parse_instant(heartbeat.updated_at)).total_seconds()
            if heartbeat
            else None
        )
        return {
            "worker": "ONLINE" if age is not None and age < 200 else "OFFLINE",
            "last_seen": heartbeat.updated_at if heartbeat else None,
        }


@app.get("/api/v1/conversations/{conversation_id}/messages", dependencies=[Depends(require_user)])
def history(conversation_id: str, offset: int = 0):
    if offset < 0:
        raise ValueError("Desplazamiento inválido.")
    with DB() as db:
        get_item(db, conversation_id, "conversations")
        rows = db.scalars(
            select(Item)
            .where(Item.kind == "messages", Item.data["conversation_id"].as_string() == conversation_id)
            .order_by(Item.created_at.desc())
            .offset(offset)
            .limit(201)
        ).all()
        return {"messages": [item_json(row) for row in reversed(rows[:200])], "has_more": len(rows) > 200}


@app.get("/api/v1/schedules", dependencies=[Depends(require_user)])
def schedules():
    with DB() as db:
        return [schedule_json(row) for row in db.scalars(select(Schedule).order_by(Schedule.next_run))]


@app.post("/api/v1/schedules", dependencies=[Depends(require_user)])
def create_schedule(body: ScheduledCommand):
    instant = parse_instant(body.run_at)
    if instant <= datetime.now(timezone.utc):
        raise ValueError("Elige una fecha futura.")
    if 0 < body.interval_minutes < 5:
        raise ValueError("El intervalo mínimo es de cinco minutos.")
    with DB() as db:
        if body.project_id:
            get_item(db, body.project_id, "projects")
        if len(list(db.scalars(select(Schedule.id)))) >= 100:
            raise ValueError("Máximo 100 automatizaciones por instalación.")
        row = Schedule(
            title=body.title,
            goal=body.goal,
            mode=body.mode,
            project_id=body.project_id,
            next_run=instant.isoformat(),
            interval_minutes=body.interval_minutes,
        )
        db.add(row)
        audit(db, "schedule.created")
        db.commit()
        return schedule_json(row)


@app.put("/api/v1/schedules/{schedule_id}", dependencies=[Depends(require_user)])
def enable_schedule(schedule_id: str, body: Enabled):
    with DB() as db:
        row = db.get(Schedule, schedule_id)
        if not row:
            raise HTTPException(404, "Automatización no encontrada.")
        if body.enabled and parse_instant(row.next_run) < datetime.now(timezone.utc):
            raise HTTPException(409, "La fecha ya pasó. Crea una nueva programación para reanudarla.")
        row.enabled = body.enabled
        audit(db, "schedule.toggled")
        db.commit()
        return schedule_json(row)


@app.delete("/api/v1/schedules/{schedule_id}", dependencies=[Depends(require_user)])
def delete_schedule(schedule_id: str):
    with DB() as db:
        row = db.get(Schedule, schedule_id)
        if not row:
            raise HTTPException(404)
        db.delete(row)
        audit(db, "schedule.deleted")
        db.commit()
    return {"deleted": True}


app.include_router(capabilities_router)
app.include_router(integrations_router)

static = Path(os.getenv("WEB_DIR", "dist-local")).resolve()
if static.exists():
    app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        if path == "manifest.webmanifest":
            return FileResponse(static / path, media_type="application/manifest+json", headers={"Cache-Control": "no-cache"})
        if path == "sw.js":
            return FileResponse(static / path, media_type="application/javascript", headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})
        return FileResponse(static / "index.html", headers={"Cache-Control": "no-cache"})
