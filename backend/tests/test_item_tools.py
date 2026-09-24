import pytest
from sqlalchemy import select

from pablo.commands import explicit_plan
from pablo.db import DB, Approval, Chunk, Item, Run
from pablo.item_tools import create_item, delete_item, update_item
from pablo.worker import process


def execute(client, tool, arguments):
    response = client.post("/api/v1/tool-runs", json={"tool": tool, "arguments": arguments})
    assert response.status_code == 200, response.text
    run_id = response.json()["id"]
    process(run_id)
    with DB() as db:
        approval = db.scalar(select(Approval).where(Approval.run_id == run_id))
        assert approval
        approval_id = approval.id
    assert client.post(f"/api/v1/approvals/{approval_id}", json={"approve": True}).status_code == 200
    process(run_id)
    process(run_id)
    with DB() as db:
        run = db.get(Run, run_id)
        assert run.status == "COMPLETED", run.result


def test_crud_through_worker(client):
    execute(client, "items.create", {"kind": "tasks", "values": {"title": "Comprar pan"}})
    execute(client, "items.update", {"kind": "tasks", "title": "Comprar pan", "changes": {"priority": "HIGH", "status": "DONE"}})
    with DB() as db:
        item = db.scalar(select(Item).where(Item.kind == "tasks"))
        assert item.data["status"] == "DONE"
        assert item.data["priority"] == "HIGH"
    execute(client, "items.delete", {"kind": "tasks", "title": "Comprar pan"})
    with DB() as db:
        assert db.scalar(select(Item).where(Item.kind == "tasks")) is None


def test_ambiguous_names_and_changed_version_rejected(client):
    with DB() as db:
        a = create_item(db, {"kind": "tasks", "values": {"title": "Duplicada"}}, None)
        create_item(db, {"kind": "tasks", "values": {"title": "Duplicada"}}, None)
        with pytest.raises(ValueError, match="único"):
            delete_item(db, {"kind": "tasks", "title": "Duplicada"}, None)
        update_item(db, {"kind": "tasks", "id": a["id"], "changes": {"priority": "HIGH"}}, None)
        with pytest.raises(ValueError, match="cambió"):
            delete_item(db, {"kind": "tasks", "id": a["id"], "version": 1}, None)


def test_document_rename_preserves_all_chunks(client):
    with DB() as db:
        created = create_item(db, {"kind": "documents", "values": {"title": "Notas", "content": "abc " * 1200}}, None)
        before = [r.text for r in db.scalars(select(Chunk).where(Chunk.document_id == created["id"]).order_by(Chunk.position))]
        row = db.get(Item, created["id"])
        row.data = row.data | {"description": row.data["description"][:500]}
        update_item(db, {"kind": "documents", "id": row.id, "changes": {"title": "Apuntes"}}, None)
        after = [r.text for r in db.scalars(select(Chunk).where(Chunk.document_id == row.id).order_by(Chunk.position))]
        assert before == after


def test_task_dependencies_and_project_children_protected(client):
    with DB() as db:
        project = create_item(db, {"kind": "projects", "values": {"title": "Curso"}}, None)
        task = create_item(db, {"kind": "tasks", "values": {"title": "Leer"}}, project["id"])
        create_item(db, {"kind": "tasks", "values": {"title": "Practicar", "dependencies": [task["id"]]}}, project["id"])
        with pytest.raises(ValueError, match="depende"):
            delete_item(db, {"kind": "tasks", "id": task["id"]}, None)
        delete_item(db, {"kind": "projects", "id": project["id"]}, None)
        assert db.get(Item, task["id"]).data["project_id"] is None


def test_batch_titles_and_exact_updates(client):
    plan = explicit_plan("Añade como tareas:\n- Comprar pan\n- Estudiar Python\n- Llamar a Ana", "DO")
    assert [s.arguments["title"] for s in plan.steps] == ["Comprar pan", "Estudiar Python", "Llamar a Ana"]
    assert explicit_plan('Completa la tarea "Estudiar Python"', "DO").steps[0].arguments["changes"] == {"status": "DONE"}
    assert explicit_plan('Borra el documento "Notas"', "ASK") is None


@pytest.mark.parametrize("kind,values", [
    ("projects", {}), ("memory", {}), ("workflows", {}), ("artifacts", {"content": "Texto"}),
    ("drafts", {"content": "Borrador"}), ("documents", {"content": "Documento"}),
    ("calendar", {"start": "2030-01-01T10:00:00+01:00", "end": "2030-01-01T11:00:00+01:00"}),
])
def test_other_item_lifecycles(client, kind, values):
    execute(client, "items.create", {"kind": kind, "values": {"title": "Prueba", **values}})
    execute(client, "items.update", {"kind": kind, "title": "Prueba", "changes": {"title": "Renombrado"}})
    execute(client, "items.delete", {"kind": kind, "title": "Renombrado"})
    with DB() as db:
        assert db.scalar(select(Item).where(Item.kind == kind)) is None


def test_schedule_pause_edit_delete(client):
    created = client.post("/api/v1/schedules", json={"title": "Repaso", "goal": "Hola", "run_at": "2030-01-01T12:00:00+01:00"})
    assert created.status_code == 200
    execute(client, "schedules.update", {"title": "Repaso", "changes": {"enabled": False, "goal": "Revisa mis tareas"}})
    schedules = client.get("/api/v1/schedules").json()
    assert schedules[0]["enabled"] is False
    execute(client, "schedules.delete", {"title": "Repaso"})
    assert client.get("/api/v1/schedules").json() == []


def test_chat_batch_persists_each_task_once(client):
    response = client.post("/api/v1/commands", json={"mode": "DO", "goal": "Añade como tareas:\n- Comprar pan\n- Estudiar Python\n- Llamar a Ana"})
    assert response.status_code == 200
    run_id = response.json()["id"]
    for _ in range(12):
        process(run_id)
        with DB() as db:
            ids = list(db.scalars(select(Approval.id).where(Approval.run_id == run_id, Approval.status == "PENDING")))
        for approval_id in ids:
            assert client.post(f"/api/v1/approvals/{approval_id}", json={"approve": True}).status_code == 200
    with DB() as db:
        assert db.get(Run, run_id).status == "COMPLETED"
        assert sorted(db.scalars(select(Item.title).where(Item.kind == "tasks"))) == ["Comprar pan", "Estudiar Python", "Llamar a Ana"]


def test_edit_after_approval_does_not_delete_changed_item(client):
    execute(client, "items.create", {"kind": "tasks", "values": {"title": "Conservar"}})
    result = client.post("/api/v1/tool-runs", json={"tool": "items.delete", "arguments": {"kind": "tasks", "title": "Conservar"}}).json()
    process(result["id"])
    with DB() as db:
        approval_id = db.scalar(select(Approval.id).where(Approval.run_id == result["id"]))
        update_item(db, {"kind": "tasks", "title": "Conservar", "changes": {"priority": "HIGH"}}, None)
        db.commit()
    client.post(f"/api/v1/approvals/{approval_id}", json={"approve": True})
    process(result["id"])
    with DB() as db:
        assert db.get(Run, result["id"]).status == "FAILED"
        assert db.scalar(select(Item).where(Item.kind == "tasks")) is not None


def test_delete_zero_task_project_with_history_and_schedule(client):
    from pablo.db import Schedule
    with DB() as db:
        project = create_item(db, {"kind": "projects", "values": {"title": "Proyecto vacío"}}, None)
        conversation = Item(kind="conversations", title="Historial", data={"project_id": project["id"]})
        schedule = Schedule(title="Repaso", goal="Hola", project_id=project["id"], next_run="2030-01-01T10:00:00+00:00")
        db.add_all([conversation, schedule])
        db.commit()
        conversation_id, schedule_id = conversation.id, schedule.id
    response = client.delete("/api/v1/items/" + project["id"])
    assert response.status_code == 200, response.text
    with DB() as db:
        assert db.get(Item, project["id"]) is None
        assert db.get(Item, conversation_id).data["project_id"] is None
        assert db.get(Schedule, schedule_id).enabled is False
        assert db.get(Schedule, schedule_id).project_id is None
