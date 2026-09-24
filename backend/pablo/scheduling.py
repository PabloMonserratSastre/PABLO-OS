"""Atomic scheduler: an occurrence and its queued run are committed together."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update

from .db import DB, Item, Run, Schedule, audit
from .schemas import Command


def create_execution(db, body: Command):
    if body.conversation_id:
        conversation = db.get(Item, body.conversation_id)
        if not conversation or conversation.kind != "conversations":
            raise ValueError("Conversación no encontrada.")
    else:
        conversation = Item(kind="conversations", title=body.goal[:80], data={"project_id": body.project_id})
        db.add(conversation)
        db.flush()
    run = Run(goal=body.goal, mode=body.mode, project_id=body.project_id, conversation_id=conversation.id)
    db.add(run)
    db.flush()
    db.add(
        Item(
            kind="messages",
            title="Tú",
            data={"conversation_id": conversation.id, "role": "user", "content": body.goal, "run_id": run.id},
        )
    )
    audit(db, "command.received", run_id=run.id)
    return run


def parse_instant(value: str) -> datetime:
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Fecha de ejecución no válida.")
    if instant.tzinfo is None:
        raise ValueError("La fecha necesita una zona horaria.")
    return instant.astimezone(timezone.utc)


def dispatch_due(at: datetime | None = None) -> int:
    instant = at or datetime.now(timezone.utc)
    count = 0
    with DB() as db:
        active = db.scalar(
            select(func.count())
            .select_from(Run)
            .where(Run.status.in_(["QUEUED", "RUNNING", "WAITING_APPROVAL"]))
        )
        room = max(0, 20 - active)
        due = (
            db.scalars(
                select(Schedule)
                .where(Schedule.enabled.is_(True), Schedule.next_run <= instant.isoformat())
                .order_by(Schedule.next_run)
                .limit(room)
            ).all()
            if room
            else []
        )
        for schedule in due:
            previous = schedule.next_run
            if schedule.interval_minutes:
                base = parse_instant(previous)
                interval = timedelta(minutes=schedule.interval_minutes)
                periods = (instant - base) // interval + 1
                upcoming = (base + periods * interval).isoformat()
            else:
                upcoming = previous
            claimed = db.execute(
                update(Schedule)
                .where(Schedule.id == schedule.id, Schedule.enabled.is_(True), Schedule.next_run == previous)
                .values(next_run=upcoming, enabled=bool(schedule.interval_minutes))
            )
            if not claimed.rowcount:
                continue
            if schedule.project_id:
                project = db.get(Item, schedule.project_id)
                if not project or project.kind != "projects":
                    schedule.enabled = False
                    audit(db, "schedule.project_missing", "ERROR")
                    continue
            run = create_execution(
                db, Command(goal=schedule.goal, mode=schedule.mode, project_id=schedule.project_id)
            )
            schedule.last_run_id = run.id
            audit(db, "schedule.dispatched", run_id=run.id, schedule_id=schedule.id)
            count += 1
        db.commit()
    return count
