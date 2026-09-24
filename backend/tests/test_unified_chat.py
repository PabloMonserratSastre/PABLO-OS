import pytest
from pablo.db import DB, Run, Approval, Item
from pablo.providers import CompatibleProvider
from pablo.schemas import Plan
from pablo.worker import process
from sqlalchemy import select


@pytest.mark.parametrize("goal", ["Hola", "Propón un plan sin crear nada"])
def test_chat_response_without_actions(client, monkeypatch, goal):
    monkeypatch.setenv("AI_API_KEY", "test")
    monkeypatch.setenv("AI_MODEL", "test")
    monkeypatch.setattr(CompatibleProvider, "plan", lambda *a: (Plan(summary="Respuesta breve", steps=[]), {"synthesis": True}))
    def forbidden(*args):
        raise AssertionError("No second model call for direct replies")
    monkeypatch.setattr(CompatibleProvider, "answer", forbidden)
    row = client.post('/api/v1/commands', json={"goal": goal, "mode": "CHAT"}).json()
    process(row['id']); process(row['id'])
    with DB() as db:
        run = db.get(Run, row['id'])
        assert run.status == 'COMPLETED' and run.result.strip() == 'Respuesta breve'
        assert not db.scalars(select(Item).where(Item.kind == 'tasks')).all()


def test_chat_mutation_keeps_approval(client, monkeypatch):
    monkeypatch.setenv("AI_API_KEY", "test")
    monkeypatch.setenv("AI_MODEL", "test")
    monkeypatch.setattr(CompatibleProvider, "plan", lambda *a: (Plan(summary="Crear tarea", steps=[{"tool": "tasks.create", "arguments": {"title": "Prueba chat"}}]), {}))
    row = client.post('/api/v1/commands', json={"goal": "Apunta una tarea nueva para practicar", "mode": "CHAT"}).json()
    process(row['id']); process(row['id'])
    with DB() as db:
        assert db.get(Run,row['id']).status == 'WAITING_APPROVAL'
        approval = db.scalar(select(Approval).where(Approval.run_id == row['id']))
        aid = approval.id
    client.post(f'/api/v1/approvals/{aid}', json={"approve": True})
    for _ in range(3): process(row['id'])
    with DB() as db:
        assert db.get(Run,row['id']).status == 'COMPLETED'
        assert db.scalar(select(Item).where(Item.kind == 'tasks')).title == 'Prueba chat'
