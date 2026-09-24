"""Deleting a project preserves its contents in the general workspace."""
import time

from sqlalchemy import select

from .db import Item, Run, Schedule, now


def detach_project(db, project_id):
    terminal = {"COMPLETED", "FAILED", "CANCELLED", "PLANNED", "BLOCKED"}
    runs = db.scalars(select(Run).where(Run.project_id == project_id)).all()
    if any(r.id != db.info.get("executing_run_id") and
           (r.status not in terminal or (r.lease_until and r.lease_until > time.time())) for r in runs):
        raise ValueError("Detén las ejecuciones del proyecto y espera a que terminen antes de eliminarlo.")
    for child in db.scalars(select(Item).where(Item.id != project_id, Item.data["project_id"].as_string() == project_id)):
        child.data = child.data | {"project_id": None}
        child.version += 1
        child.updated_at = now()
    for schedule in db.scalars(select(Schedule).where(Schedule.project_id == project_id)):
        schedule.project_id = None
        schedule.enabled = False
    for run in runs:
        run.project_id = None
