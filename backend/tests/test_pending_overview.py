import pytest

from pablo.commands import explicit_plan
from pablo.db import DB, Item, Run
from pablo.providers import CompatibleProvider
from pablo.worker import process


@pytest.mark.parametrize("goal", ["dime las tareas y proyectos que tengo pendientes", "muestra mis proyectos y tareas pendientes"])
def test_pending_overview_without_selected_project(client, monkeypatch, goal):
    def forbidden(*a, **kw):
        raise AssertionError("Basic overview must not call the provider")
    monkeypatch.setattr(CompatibleProvider, "request", forbidden)
    with DB() as db:
        db.add(Item(kind="projects", title="Proyecto activo", data={"status":"PLANNING"}))
        db.add(Item(kind="projects", title="Proyecto finalizado", data={"status":"COMPLETED"}))
        db.add(Item(kind="tasks", title="Tarea pendiente", data={"status":"TODO"}))
        db.commit()
    run = client.post('/api/v1/commands', json={"goal":goal,"mode":"CHAT"}).json()
    for _ in range(5):
        process(run['id'])
    with DB() as db:
        row=db.get(Run,run['id'])
        assert row.status == 'COMPLETED'
        assert 'Proyecto activo' in row.result and 'Tarea pendiente' in row.result
        assert 'Proyecto finalizado' not in row.result


def test_overview_preserves_additional_constraints():
    assert explicit_plan('dime las tareas y proyectos pendientes de Ana', 'CHAT') is None


@pytest.mark.parametrize("day,offset", [("hoy",0),("mañana",1),("ayer",-1),("pasado mañana",2)])
def test_relative_calendar_uses_google_and_local_day(day, offset):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    plan=explicit_plan(f"dime que eventos tengo {day} en el calendario", "CHAT", "Europe/Madrid")
    step=plan.steps[0]
    assert step.tool == "google_calendar.list"
    begin=datetime.fromisoformat(step.arguments["start"])
    end=datetime.fromisoformat(step.arguments["end"])
    assert begin.date() == datetime.now(ZoneInfo("Europe/Madrid")).date()+timedelta(days=offset)
    assert begin.hour == end.hour == 0
    assert end.date()-begin.date() == timedelta(days=1)
    assert explicit_plan(f"dime que eventos tengo {day} en el calendario local", "CHAT") is None
