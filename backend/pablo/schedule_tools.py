"""Edit and remove scheduled commands without replaying previous occurrences."""
from datetime import datetime, timezone

from sqlalchemy import select

from .db import Schedule
from .scheduling import parse_instant
from .schemas import ScheduledCommand


def snapshot(row):
    return {"title": row.title, "goal": row.goal, "mode": row.mode, "project_id": row.project_id,
            "run_at": row.next_run, "interval_minutes": row.interval_minutes, "enabled": row.enabled}


def resolve(db, args, project_id):
    query = select(Schedule)
    if args.get("id"):
        query = query.where(Schedule.id == args["id"])
    elif args.get("title"):
        query = query.where(Schedule.title == args["title"])
    else:
        raise ValueError("Indica el ID o título exacto de la automatización.")
    if project_id:
        query = query.where(Schedule.project_id == project_id)
    rows = db.scalars(query).all()
    if len(rows) != 1:
        raise ValueError("No hay una única automatización con ese nombre. Utiliza su ID.")
    row = rows[0]
    if "expected" in args and snapshot(row) != args["expected"]:
        raise ValueError("La automatización cambió desde la aprobación. Solicita la acción de nuevo.")
    return row


def list_schedules(db, args, project_id):
    query = select(Schedule)
    if project_id:
        query = query.where(Schedule.project_id == project_id)
    return [{"id": row.id, **snapshot(row)} for row in db.scalars(query.limit(100))]


def update_schedule(db, args, project_id):
    from .capabilities import project_exists
    row = resolve(db, args, project_id)
    changes = args.get("changes")
    if not isinstance(changes, dict) or not changes:
        raise ValueError("Indica los campos de la automatización que quieres cambiar.")
    values = snapshot(row) | changes
    enabled = values.pop("enabled")
    if type(enabled) is not bool:
        raise ValueError("enabled debe ser true o false.")
    body = ScheduledCommand.model_validate(values)
    instant = parse_instant(body.run_at)
    if enabled and instant <= datetime.now(timezone.utc):
        raise ValueError("Indica una fecha futura para activar la automatización.")
    if 0 < body.interval_minutes < 5:
        raise ValueError("El intervalo mínimo es de cinco minutos.")
    project_exists(db, body.project_id)
    for name, value in body.model_dump(exclude={"run_at"}).items():
        setattr(row, name, value)
    row.next_run, row.enabled = instant.isoformat(), enabled
    db.flush()
    return {"id": row.id, **snapshot(row), "verified": True}


def delete_schedule(db, args, project_id):
    row = resolve(db, args, project_id)
    result = {"id": row.id, "title": row.title, "deleted": True, "verified": True}
    db.delete(row)
    db.flush()
    return result


def register(registry, tool):
    registry.register(tool("schedules.list", "SAFE", "Automation", list_schedules))
    registry.register(tool("schedules.update", "MODERATE", "Automation", update_schedule))
    registry.register(tool("schedules.delete", "HIGH", "Automation", delete_schedule))
