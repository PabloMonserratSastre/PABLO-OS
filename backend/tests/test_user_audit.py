"""Formal/informal requests through API + worker, with disposable data and fake Google.

These cases verify routing, execution and presentation, not live model intelligence.
The parametrized request names are retained in the audit JUnit report.
"""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from test_flows import run_until_pause

from pablo.commands import explicit_plan
from pablo.db import DB, Item
from pablo.providers import CompatibleProvider
from pablo.tools import Tool, registry
from pablo.workspace_tools import code_scaffold

READ_CASES = [
    ("dime mis tareas pendientes", ["tasks.list"]),
    ("¿Qué tareas tengo pendientes?", ["tasks.list"]),
    ("Oye, muéstrame mis tareas, porfa", ["tasks.list"]),
    ("Podrías mostrarme mis tareas pendientes, por favor", ["tasks.list"]),
    ("Por favor, muestra mis proyectos pendientes", ["projects.list"]),
    ("¿Qué proyectos tengo pendientes?", ["projects.list"]),
    ("Buenas, dime las tareas y proyectos que tengo pendientes", ["tasks.list", "projects.list"]),
    ("MUESTRAME MIS PROYECTOS Y TAREAS PENDIENTES", ["tasks.list", "projects.list"]),
    ("  dime   tareas pendientes  ", ["tasks.list"]),
    ("¿Puedes decirme que tareas tengo pendientes?", ["tasks.list"]),
    ("prepara mi resumen diario", ["daily.summary"]),
    ("Dame el resumen de hoy, porfa", ["daily.summary"]),
    ("¿Qué día es hoy?", []),
    ("Oye, a qué fecha estamos", []),
]
CALENDAR_CASES = [
    f"{prefix}{query}{suffix}"
    for prefix, suffix in [("", ""), ("¿", "?"), ("Oye, ", ", porfa"), ("Por favor, ", "")]
    for query in ["qué eventos tengo mañana en el calendario", "que tengo hoy", "muestra mi agenda pasado mañana", "consulta mis eventos ayer en Google Calendar"]
]


@pytest.mark.parametrize("goal,expected", READ_CASES + [(g, ["google_calendar.list"]) for g in CALENDAR_CASES])
def test_requests_reach_tools_and_visible_answer(client, monkeypatch, goal, expected):
    def forbidden(*args, **kwargs):
        raise AssertionError("Routine exact requests must not spend provider quota")
    monkeypatch.setattr(CompatibleProvider, "request", forbidden)
    calls = []
    def google(db, args, project):
        calls.append(args)
        begin, end = datetime.fromisoformat(args["start"]), datetime.fromisoformat(args["end"])
        assert begin.tzinfo is not None and end.tzinfo is not None
        assert end.date() - begin.date() == timedelta(days=1)
        assert begin.hour == end.hour == 0
        return {"timezone": "Europe/Madrid", "events": [{"summary": "Reunión de prueba", "start": {"dateTime": begin.replace(hour=10).isoformat()}}]}
    monkeypatch.setitem(registry.tools, "google_calendar.list", Tool("google_calendar.list", "SAFE", "Google", google))
    monkeypatch.setitem(registry.tools, "daily.summary", Tool("daily.summary", "SAFE", "Productivity", lambda *a: {"text": "Hola Pablo, este es tu resumen diario de prueba."}))
    with DB() as db:
        db.add(Item(kind="tasks", title="Comprar pan", data={"status": "TODO"}))
        db.add(Item(kind="tasks", title="Ya terminada", data={"status": "DONE"}))
        db.add(Item(kind="projects", title="Proyecto activo", data={"status": "PLANNING"}))
        db.commit()
    response = client.post("/api/v1/commands", json={"mode": "CHAT", "goal": goal})
    assert response.status_code == 200
    run = run_until_pause(response.json()["id"])
    assert run.status == "COMPLETED", run.result
    assert [s["tool"] for s in run.plan] == expected
    assert run.result.strip() and "```json" not in run.result and "Síntesis IA" not in run.result
    if "tasks.list" in expected:
        assert "Comprar pan" in run.result and "Ya terminada" not in run.result
    if "projects.list" in expected:
        assert "Proyecto activo" in run.result
    if "google_calendar.list" in expected:
        assert len(calls) == 1 and "Reunión de prueba" in run.result
    if not expected:
        assert datetime.now(ZoneInfo("Europe/Madrid")).strftime("%d/%m/%Y") in run.result


@pytest.mark.parametrize("goal", [
    "dime las tareas pendientes de Ana", "dime proyectos completados", "lista todas las tareas incluidas las completadas",
    "que eventos tengo mañana en el calendario local", "que eventos tengo mañana y el viernes", "que tengo mañana a las 10",
    "crea una tarea llamada Pan y borra todas las demás", "crea tareas: Pan; Leche. No ejecutes nada",
    "añade tareas: Pan, sin guardar", "crea una tarea llamada Pan para mañana",
    "muestra mis tareas pendientes y envíalas por correo", "dame el resumen diario de ayer",
])
def test_extra_constraints_are_not_silently_discarded(goal):
    assert explicit_plan(goal, "CHAT") is None


@pytest.mark.parametrize("goal,titles", [
    ('Crea una tarea llamada "Comprar pan"', ["Comprar pan"]),
    ('añade una tarea titulada "Aprender Python"', ["Aprender Python"]),
    ('Agrega tarea con título "Revisar informes"', ["Revisar informes"]),
    ('Añade como tareas:\n- Comprar pan\n- Estudiar', ["Comprar pan", "Estudiar"]),
    ('apunta tareas: Pasear; Leer', ["Pasear", "Leer"]),
    ('CREAR UNA TAREA LLAMADA "Año nuevo"', ["Año nuevo"]),
])
def test_mutations_are_approved_once_and_persisted(client, goal, titles):
    row = client.post("/api/v1/commands", json={"goal": goal, "mode": "CHAT"}).json()
    for _ in titles:
        run = run_until_pause(row["id"])
        assert run.status == "WAITING_APPROVAL", run.result
        approval = next(a for a in client.get("/api/v1/state").json()["approvals"] if a["run_id"] == row["id"])
        assert client.post(f'/api/v1/approvals/{approval["id"]}', json={"approve": True}).status_code == 200
    assert run_until_pause(row["id"]).status == "COMPLETED"
    run_until_pause(row["id"])
    with DB() as db:
        assert sorted(i.title for i in db.scalars(select(Item).where(Item.kind == "tasks"))) == sorted(titles)


def test_two_custom_websites_are_separate_and_keep_contents(tmp_path, monkeypatch):
    monkeypatch.setenv("PABLO_WORKSPACE_ROOT", str(tmp_path))
    for name, heading in [("Restaurante", "Nuestro menú"), ("Portfolio", "Mis trabajos")]:
        result = code_scaffold(None, {"name": name, "kind": "web", "html": f'<!doctype html><html><head></head><body><h1>{heading}</h1></body></html>', "css": "h1 {color: navy}", "javascript": "document.title='Prueba';"}, None)
        folder = tmp_path / result["path"]
        assert {"index.html", "styles.css", "script.js", "project.json"}.issubset(p.name for p in folder.iterdir())
        assert heading in (folder / "index.html").read_text(encoding="utf-8")
        assert json.loads((folder / "project.json").read_text(encoding="utf-8"))["name"] == name
    first = (tmp_path / "restaurante" / "index.html").read_bytes()
    with pytest.raises(ValueError):
        code_scaffold(None, {"name": "Restaurante", "kind": "web", "html": "overwrite"}, None)
    assert (tmp_path / "restaurante" / "index.html").read_bytes() == first
    assert not (tmp_path / "index.html").exists()


def test_invalid_website_leaves_no_partial_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("PABLO_WORKSPACE_ROOT", str(tmp_path))
    with pytest.raises(ValueError):
        code_scaffold(None, {"name": "Invalid", "kind": "web", "html": "<h1>Hola</h1>", "javascript": "x" * 200001}, None)
    assert not (tmp_path / "invalid").exists()


@pytest.mark.parametrize("weekday", ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"])
def test_weekdays_are_computed_not_guessed(weekday):
    plan = explicit_plan(f"Consulta por favor mi agenda de Google del próximo {weekday}, solo los eventos de ese día.", "CHAT")
    start = datetime.fromisoformat(plan.steps[0].arguments["start"])
    weekdays = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    assert start.weekday() == weekdays.index(weekday)
    assert 1 <= (start.date() - datetime.now(ZoneInfo("Europe/Madrid")).date()).days <= 7


def test_simple_request_does_not_search_documents(client, monkeypatch):
    import pablo.worker as worker
    def forbidden(*args):
        raise AssertionError("No document retrieval for a basic task query")
    monkeypatch.setattr(worker, "search", forbidden)
    row = client.post("/api/v1/commands", json={"goal": "dime mis tareas pendientes", "mode": "CHAT"}).json()
    assert run_until_pause(row["id"]).status == "COMPLETED"


def test_calendar_provider_fallback_preserves_date_bounds(client, monkeypatch):
    monkeypatch.setenv("AI_API_KEY", "test")
    monkeypatch.setenv("AI_MODEL", "test")
    monkeypatch.setattr(CompatibleProvider, "request", lambda *a: {"choices": [{"message": {"content": json.dumps({"summary": "Agenda", "steps": [{"tool": "calendar.list", "arguments": {"from": "2026-09-18T00:00:00+02:00", "to": "2026-09-19T00:00:00+02:00"}}]})}}]})
    plan, _ = CompatibleProvider().plan("Consulta mi agenda para el día indicado en la conversación", "CHAT", {})
    assert plan.steps[0].tool == "google_calendar.list"
    assert plan.steps[0].arguments == {"start": "2026-09-18T00:00:00+02:00", "end": "2026-09-19T00:00:00+02:00"}


def test_gmail_count_and_inbox_default(monkeypatch):
    import pablo.integrations as integrations
    seen = []
    def google(*args, **kwargs):
        seen.append(kwargs["params"])
        return {"messages": []}
    monkeypatch.setattr(integrations, "_google", google)
    integrations.email_list(None, {"limit": 3}, None)
    integrations.email_list(None, {"limit": 5, "query": "in:sent"}, None)
    assert seen == [{"maxResults": 3, "q": "in:inbox"}, {"maxResults": 5, "q": "in:sent"}]


@pytest.mark.parametrize("day,hours", [("2026-03-29", 23), ("2026-10-25", 25)])
def test_day_ranges_follow_daylight_saving(monkeypatch, day, hours):
    import datetime as module
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.fromisoformat(day + "T12:00:00").replace(tzinfo=ZoneInfo("Europe/Madrid")).astimezone(tz)
    monkeypatch.setattr(module, "datetime", FixedDatetime)
    plan = explicit_plan("que eventos tengo hoy", "CHAT")
    start = datetime.fromisoformat(plan.steps[0].arguments["start"])
    end = datetime.fromisoformat(plan.steps[0].arguments["end"])
    assert (end - start).total_seconds() == hours * 3600


@pytest.mark.parametrize("extra", [{}, {"mode": "CHAT"}])
def test_new_automation_uses_unified_chat(client, extra):
    from pablo.db import Schedule
    from pablo.workspace_tools import automation_create
    with DB() as db:
        result = automation_create(db, {"title": "Resumen de prueba", "goal": "dime mis tareas pendientes", "run_at": (datetime.now(ZoneInfo("Europe/Madrid")) + timedelta(days=1)).isoformat(), **extra}, None)
        assert db.get(Schedule, result["id"]).mode == "CHAT"
