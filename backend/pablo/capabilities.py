"""Authenticated product capabilities: direct tools, agenda and data lifecycle."""

import json
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import Field
from sqlalchemy import delete, select

from .configuration import ProviderSettings, public_provider, save_provider
from .cloud_workspace import cloud_view
from .db import DB, Approval, Audit, Base, Chunk, Item, Owner, Run, Schedule, ServiceConfig, audit, now, uid
from .knowledge import index
from .scheduling import create_execution, parse_instant
from .schemas import Command, Strict
from .security import require_user, verify
from .tools import registry

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_user)])
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "PLANNED", "BLOCKED"}


class ToolRequest(Strict):
    tool: str = Field(max_length=80)
    arguments: dict = Field(default_factory=dict)
    project_id: str | None = None


class Event(Strict):
    title: str = Field(min_length=1, max_length=300)
    start: str
    end: str = ""
    description: str = Field(default="", max_length=20000)
    project_id: str | None = None


class Privacy(Strict):
    retention_days: int = Field(default=0, ge=0, le=3650)


class DeleteAccount(Strict):
    password: str = Field(min_length=1, max_length=256)
    confirmation: str


def record_json(row):
    return {"id": row.id, "title": row.title, **row.data, "version": row.version}


def project_exists(db, project_id):
    if project_id:
        project = db.get(Item, project_id)
        if not project or project.kind != "projects":
            raise HTTPException(404, "Proyecto no encontrado.")


def ensure_idle(db):
    if db.scalar(select(Run.id).where(
        (Run.status.not_in(TERMINAL)) | (Run.lease_until > time.time())
    ).limit(1)):
        raise HTTPException(409, "Cancela o termina las ejecuciones activas antes de continuar.")


@router.get("/tools")
def tools():
    return registry.list()


@router.get("/workspace/files")
@cloud_view
def workspace_files():
    from .workspace_tools import workspace_list
    return workspace_list(None, {"limit": 500}, None)


@router.get("/workspace/content")
@cloud_view
def workspace_content(path: str):
    from .workspace_tools import workspace_read
    return workspace_read(None, {"path": path}, None)


@router.get("/workspace/download")
@cloud_view
def download_workspace(path: str):
    from .workspace_tools import _read, workspace_path

    file = workspace_path(path, existing=True)
    _read(file)
    from urllib.parse import quote
    return Response(file.read_bytes(), media_type="application/octet-stream",
                    headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(file.name)})


@router.get("/workspace/preview/{path:path}")
@cloud_view
def preview_workspace(path: str):
    from .workspace_tools import _read, workspace_path

    file = workspace_path(path, existing=True)
    types = {".html": "text/html", ".htm": "text/html", ".css": "text/css", ".js": "application/javascript"}
    media = types.get(file.suffix.lower())
    if not media:
        raise HTTPException(415, "La vista previa admite HTML, CSS y JavaScript.")
    from .preview import preview_html
    content = preview_html(file) if media == "text/html" else _read(file)
    # Opaque origin: generated JavaScript cannot read the app session or its APIs.
    return Response(content, media_type=media, headers={
        "Content-Security-Policy": "sandbox allow-scripts allow-modals allow-forms allow-downloads; default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src data: https:; connect-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'",
        "X-Frame-Options": "SAMEORIGIN",
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
    })


@router.post("/tool-runs")
def tool_run(body: ToolRequest):
    from .main import run_json

    tool = registry.get(body.tool)
    if len(json.dumps(body.arguments)) > 60000:
        raise ValueError("Los parámetros son demasiado grandes.")
    with DB() as db:
        project_exists(db, body.project_id)
        if len(list(db.scalars(select(Run.id).where(Run.status.not_in(TERMINAL))))) >= 20:
            raise HTTPException(429, "Termina o cancela alguna ejecución antes de continuar.")
        run = create_execution(db, Command(goal=f"Usar {tool.id}", mode="DO", project_id=body.project_id))
        run.plan = [{"tool": tool.id, "arguments": body.arguments, "depends_on": [],
                     "status": "PENDING", "result": None}]
        run.status = "RUNNING"
        run.result = "Ejecución solicitada desde el panel de herramientas."
        run.usage = {"provider": "DIRECT", "retries": 0}
        if tool.id == "code.run":
            run.result += " El código se ejecuta con tus permisos de Windows; el directorio de trabajo no es un aislamiento del sistema operativo."
        db.commit()
        return run_json(run)


@router.get("/provider")
def get_provider():
    with DB() as db:
        return public_provider(db)


@router.get("/provider/local-status")
def local_provider_status():
    """Discover installed Ollama models without loading one or sending user data."""
    import httpx

    try:
        with httpx.Client(timeout=3, follow_redirects=False, trust_env=False) as client:
            response = client.get("http://127.0.0.1:11434/api/tags")
            response.raise_for_status()
            data = response.json()
        rows = data.get("models") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise ValueError("invalid models")
        models = [{"name": row["name"], "size": row.get("size", 0)} for row in rows
                  if isinstance(row, dict) and isinstance(row.get("name"), str)]
        return {"available": True, "models": models,
                "message": "Ollama está conectado." if models else "Ollama funciona, pero todavía no hay modelos descargados."}
    except (httpx.HTTPError, ValueError):
        return {"available": False, "models": [],
                "message": "No se pudo conectar con Ollama. Ábrelo desde el menú Inicio y vuelve a comprobar."}


@router.put("/provider")
def set_provider(body: ProviderSettings):
    with DB() as db:
        save_provider(db, body)
        audit(db, "provider.configured")
        db.commit()
        return public_provider(db)


@router.get("/calendar")
def calendar():
    with DB() as db:
        rows = db.scalars(select(Item).where(Item.kind == "calendar")).all()
        return sorted([record_json(row) for row in rows], key=lambda row: row.get("start", ""))


def event_data(body):
    start = parse_instant(body.start)
    end = parse_instant(body.end) if body.end else start + timedelta(hours=1)
    if end <= start:
        raise ValueError("El final debe ser posterior al inicio.")
    return body.model_dump(exclude={"title"}) | {"start": start.isoformat(), "end": end.isoformat()}


@router.post("/calendar")
def calendar_create(body: Event):
    data = event_data(body)
    with DB() as db:
        project_exists(db, body.project_id)
        row = Item(kind="calendar", title=body.title.strip(), data=data)
        if not row.title:
            raise ValueError("El evento necesita un título.")
        db.add(row)
        audit(db, "calendar.created")
        db.commit()
        return record_json(row)


@router.patch("/calendar/{event_id}")
def calendar_update(event_id: str, body: Event):
    data = event_data(body)
    with DB() as db:
        row = db.get(Item, event_id)
        if not row or row.kind != "calendar":
            raise HTTPException(404, "Evento no encontrado.")
        project_exists(db, body.project_id)
        if not body.title.strip():
            raise ValueError("El evento necesita un título.")
        row.title, row.data = body.title.strip(), data
        row.version += 1
        row.updated_at = now()
        audit(db, "calendar.updated")
        db.commit()
        return record_json(row)


@router.delete("/calendar/{event_id}")
def calendar_delete(event_id: str):
    with DB() as db:
        row = db.get(Item, event_id)
        if not row or row.kind != "calendar":
            raise HTTPException(404, "Evento no encontrado.")
        db.delete(row)
        audit(db, "calendar.deleted")
        db.commit()
    return {"deleted": True}


@router.post("/documents/{document_id}/reindex")
def reindex(document_id: str):
    with DB() as db:
        doc = db.get(Item, document_id)
        if not doc or doc.kind != "documents":
            raise HTTPException(404, "Documento no encontrado.")
        old = db.scalars(select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.position)).all()
        from .knowledge import restore_text
        content = restore_text(old)
        if not content:
            raise ValueError("El documento no tiene texto recuperable. Vuelve a subirlo.")
        version = doc.version
    from .knowledge import prepare_vectors

    vectors = prepare_vectors(content)
    with DB() as db:
        doc = db.get(Item, document_id)
        if not doc or doc.version != version:
            raise HTTPException(409, "El documento cambió durante la indexación.")
        db.execute(delete(Chunk).where(Chunk.document_id == document_id))
        count = index(db, document_id, content, vectors=vectors)
        doc.data = doc.data | {"chunks": count, "status": "INDEXED"}
        doc.version += 1
        audit(db, "document.reindexed", chunks=count)
        db.commit()
        return record_json(doc)


@router.get("/privacy")
def privacy():
    with DB() as db:
        row = db.get(ServiceConfig, "privacy")
        return row.value if row else Privacy().model_dump()


@router.put("/privacy")
def privacy_update(body: Privacy):
    with DB() as db:
        db.merge(ServiceConfig(id="privacy", value=body.model_dump(), encrypted=""))
        audit(db, "privacy.updated")
        db.commit()
    return body


def apply_retention():
    with DB() as db:
        row = db.get(ServiceConfig, "privacy")
        days = row.value.get("retention_days", 0) if row else 0
        if not days:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        ids = list(db.scalars(select(Run.id).where(
            Run.updated_at < cutoff, Run.status.in_(TERMINAL),
            (Run.lease_until.is_(None)) | (Run.lease_until < time.time()),
        )))
        if ids:
            db.execute(delete(Approval).where(Approval.run_id.in_(ids)))
            db.execute(delete(Item).where(Item.kind == "messages", Item.data["run_id"].as_string().in_(ids)))
            db.execute(delete(Audit).where(Audit.run_id.in_(ids)))
            for schedule in db.scalars(select(Schedule).where(Schedule.last_run_id.in_(ids))):
                schedule.last_run_id = None
            db.execute(delete(Run).where(Run.id.in_(ids)))
        db.execute(delete(Audit).where(Audit.created_at < cutoff, Audit.run_id.is_(None)))
        db.commit()
        return len(ids)


@router.delete("/account")
def delete_account(body: DeleteAccount, response: Response):
    with DB() as db:
        owner = db.get(Owner, 1)
        if body.confirmation != "ELIMINAR MI CUENTA" or not verify(body.password, owner.password):
            raise HTTPException(403, "La contraseña o la confirmación no coincide.")
        ensure_idle(db)
        for table in reversed(Base.metadata.sorted_tables):
            if table.name != "runtime_status":
                db.execute(delete(table))
        db.commit()
    response.delete_cookie("pablo_session")
    return {"deleted": True, "detail": "Cuenta, historial y conexiones eliminados. Las copias de seguridad y archivos generados se conservan en disco."}


@router.post("/import")
def import_data(body: dict):
    if body.get("schema_version") not in {2, 3}:
        raise ValueError("Formato de copia no compatible (se requiere versión 2 o 3).")
    rows, chunks, schedules = body.get("items", []), body.get("document_chunks", []), body.get("schedules", [])
    if not all(isinstance(value, list) for value in [rows, chunks, schedules]):
        raise ValueError("Copia no válida.")
    if len(rows) > 10000 or len(chunks) > 10000 or len(schedules) > 100:
        raise ValueError("La copia excede los límites de importación.")
    allowed = {"projects", "tasks", "memory", "documents", "artifacts", "conversations", "messages", "workflows", "calendar", "drafts"}
    ids = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or row.get("kind") not in allowed:
            raise ValueError("La copia contiene un registro no válido.")
        if row["id"] in ids:
            raise ValueError("La copia contiene identificadores duplicados.")
        if not isinstance(row.get("title"), str) or not 1 <= len(row["title"]) <= 300:
            raise ValueError("Título de registro no válido.")
        ids[row["id"]] = uid()
    kinds = {row["id"]: row["kind"] for row in rows}
    for row in rows:
        project = row.get("project_id")
        if project and kinds.get(project) != "projects":
            raise ValueError("La copia contiene vínculos a proyectos ausentes.")
        if row.get("kind") == "messages" and kinds.get(row.get("conversation_id")) != "conversations":
            raise ValueError("La copia contiene mensajes sin conversación.")
    with DB() as db:
        ensure_idle(db)
        for row in rows:
            data = {k: v for k, v in row.items() if k not in {"id", "kind", "title", "version", "created_at", "updated_at", "run_id"}}
            for key in ["project_id", "conversation_id"]:
                if data.get(key):
                    data[key] = ids.get(data[key])
            if "dependencies" in data:
                if not isinstance(data["dependencies"], list) or len(data["dependencies"]) > 30:
                    raise ValueError("Dependencias no válidas en la copia.")
                if any(kinds.get(dep) != "tasks" for dep in data["dependencies"]):
                    raise ValueError("La copia contiene dependencias ausentes.")
                data["dependencies"] = [ids[dep] for dep in data["dependencies"]]
            db.add(Item(id=ids[row["id"]], kind=row["kind"], title=row["title"], data=data))
        for chunk in chunks:
            if (not isinstance(chunk, dict) or kinds.get(chunk.get("document_id")) != "documents"
                    or not isinstance(chunk.get("position"), int) or chunk["position"] < 0
                    or not isinstance(chunk.get("text"), str) or len(chunk["text"]) > 500000):
                raise ValueError("La copia contiene fragmentos no válidos.")
            db.add(Chunk(document_id=ids[chunk["document_id"]], position=chunk["position"], text=chunk["text"]))
        for schedule in schedules:
            if not isinstance(schedule, dict):
                raise ValueError("Programación no válida.")
            from .schemas import ScheduledCommand

            validated = ScheduledCommand.model_validate({
                "title": schedule.get("title"), "goal": schedule.get("goal"), "mode": schedule.get("mode", "ASK"),
                "project_id": ids.get(schedule.get("project_id")), "run_at": schedule.get("next_run"),
                "interval_minutes": schedule.get("interval_minutes", 0),
            })
            db.add(Schedule(title=validated.title, goal=validated.goal, mode=validated.mode,
                            project_id=validated.project_id, next_run=parse_instant(validated.run_at).isoformat(),
                            interval_minutes=validated.interval_minutes, enabled=False))
        audit(db, "backup.imported", records=len(rows), chunks=len(chunks), schedules=len(schedules))
        db.commit()
    return {"imported": len(rows), "chunks": len(chunks), "schedules": len(schedules),
            "detail": "Registros incorporados. Programaciones restauradas en pausa; no se reejecuta el historial."}
