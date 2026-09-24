import os

import pytest
from sqlalchemy import delete, select

from pablo.db import DB, Approval, Base, Chunk, Item, Run, engine
from pablo.worker import process


def run_until_pause(run_id):
    for _ in range(14):
        process(run_id)
        with DB() as db:
            r = db.get(Run, run_id)
            if r.status not in {"QUEUED", "RUNNING"}:
                return r
    raise AssertionError("Run did not pause")


def test_authentication_and_csrf(client):
    assert client.get("/api/v1/state").status_code == 200
    assert client.post("/api/v1/auth/setup", json={"password": "Temporary-test-pass-2026"}).status_code == 409
    assert (
        client.post("/api/v1/commands", json={"goal": "hello"}, headers={"X-Pablo-Request": ""}).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/commands", json={"goal": "hello"}, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/state").status_code == 401
    assert client.post("/api/v1/auth/login", json={"password": "Wrong-password-123"}).status_code == 401


def test_project_and_optimistic_concurrency(client):
    p = client.post("/api/v1/items/projects", json={"title": "Voxel", "status": "ACTIVE"}).json()
    data = {"title": "Updated", "status": "ACTIVE", "version": p["version"]}
    assert client.put("/api/v1/items/" + p["id"], json=data).status_code == 200
    assert client.put("/api/v1/items/" + p["id"], json=data).status_code == 409
    assert (
        client.post("/api/v1/items/tasks", json={"title": "bad", "project_id": "missing"}).status_code == 404
    )


def test_workflow_approvals_persist_and_not_replayed(client):
    p = client.post("/api/v1/items/projects", json={"title": "Voxel", "status": "ACTIVE"}).json()
    r = client.post(
        "/api/v1/commands", json={"goal": "Quiero crear un videojuego", "mode": "DO", "project_id": p["id"]}
    ).json()
    for expected in range(4):
        assert run_until_pause(r["id"]).status == "WAITING_APPROVAL"
        state = client.get("/api/v1/state").json()
        assert len([i for i in state["items"] if i["kind"] == "tasks"]) == expected
        approval = state["approvals"][0]
        assert client.post("/api/v1/approvals/" + approval["id"], json={"approve": True}).status_code == 200
        assert client.post("/api/v1/approvals/" + approval["id"], json={"approve": True}).status_code == 409
    assert run_until_pause(r["id"]).status == "COMPLETED"
    process(r["id"])
    with DB() as db:
        tasks = list(db.scalars(select(Item).where(Item.kind == "tasks")))
        assert len(tasks) == 4
        assert all(t.data["project_id"] == p["id"] for t in tasks)
        assert all(a.status == "EXECUTED" for a in db.scalars(select(Approval)))


def test_reject_prevents_changes(client):
    r = client.post("/api/v1/commands", json={"goal": "Crear proyecto", "mode": "DO"}).json()
    run_until_pause(r["id"])
    a = client.get("/api/v1/state").json()["approvals"][0]
    client.post("/api/v1/approvals/" + a["id"], json={"approve": False})
    process(r["id"])
    assert not [i for i in client.get("/api/v1/state").json()["items"] if i["kind"] == "tasks"]


def test_plan_never_executes_and_cancel(client):
    r = client.post("/api/v1/commands", json={"goal": "Crear app", "mode": "PLAN"}).json()
    assert run_until_pause(r["id"]).status == "PLANNED"
    r = client.post("/api/v1/commands", json={"goal": "Crear app", "mode": "DO"}).json()
    assert client.post("/api/v1/runs/" + r["id"] + "/cancel").status_code == 200
    process(r["id"])
    with DB() as db:
        assert db.get(Run, r["id"]).status == "CANCELLED"


def test_document_upload_retrieval_and_delete(client):
    r = client.post(
        "/api/v1/documents",
        files={
            "file": ("notes.md", "La fotosíntesis convierte energía luminosa en energía química.".encode())
        },
    )
    assert r.status_code == 200, r.text
    source = client.get("/api/v1/search", params={"q": "fotosíntesis"}).json()["sources"][0]
    assert source["source"] == "notes.md"
    assert source["method"] == "lexical"
    assert "luminosa" in source["text"]
    assert client.delete("/api/v1/items/" + r.json()["id"]).status_code == 200
    assert not client.get("/api/v1/search", params={"q": "fotosíntesis"}).json()["sources"]
    with DB() as db:
        assert not list(db.scalars(select(Chunk)))


def test_upload_invalid_and_oversized(client):
    assert client.post("/api/v1/documents", files={"file": ("a.exe", b"bad")}).status_code == 422
    assert client.post("/api/v1/documents", files={"file": ("a.txt", b"x" * 5_000_001)}).status_code == 413


def test_memory_consent(client):
    profile = client.get("/api/v1/state").json()["profile"]
    profile["memory_enabled"] = False
    assert client.put("/api/v1/settings", json=profile).status_code == 200
    assert client.post("/api/v1/items/memory", json={"title": "Private preference"}).status_code == 403


def test_task_dependency_cycles(client):
    a = client.post("/api/v1/items/tasks", json={"title": "A"}).json()
    b = client.post("/api/v1/items/tasks", json={"title": "B", "dependencies": [a["id"]]}).json()
    assert (
        client.put(
            "/api/v1/items/" + a["id"], json={"title": "A", "dependencies": [b["id"]], "version": 1}
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/api/v1/items/" + b["id"],
            json={"title": "B", "dependencies": [a["id"]], "status": "DONE", "version": 1},
        ).status_code
        == 422
    )
    assert client.delete("/api/v1/items/" + a["id"]).status_code == 409


def test_github_read_adapter(client, monkeypatch):
    from pablo import tools

    class Response:
        is_success = True

        def __init__(self, value):
            self.value = value

        def json(self):
            return self.value

    class MockClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, **kwargs):
            if url.endswith("/readme"):
                return Response({"content": "IyBURVNUIFJFUE8="})
            return Response(
                {
                    "full_name": "example/repo",
                    "html_url": "https://github.com/example/repo",
                    "default_branch": "main",
                    "open_issues_count": 2,
                    "language": "Python",
                }
            )

    monkeypatch.setattr(tools.httpx, "Client", MockClient)
    with DB() as db:
        result = tools.github_inspect(db, {"repository": "example/repo"}, None)
        assert result["readme"] == "# TEST REPO"
        with pytest.raises(ValueError):
            tools.github_inspect(db, {"repository": "https://evil.example"}, None)


def test_tool_failure_and_retry_preserves_checkpoint(client, monkeypatch):
    from pablo.tools import Tool, registry

    original = registry.tools["tasks.list"]

    def fail(*args):
        raise ValueError("Simulated bounded failure")

    monkeypatch.setitem(registry.tools, "tasks.list", Tool("tasks.list", "SAFE", "Productivity", fail))
    r = client.post("/api/v1/commands", json={"goal": "Qué tengo hoy"}).json()
    assert run_until_pause(r["id"]).status == "FAILED"
    monkeypatch.setitem(registry.tools, "tasks.list", original)
    assert client.post("/api/v1/runs/" + r["id"] + "/retry").status_code == 200
    assert run_until_pause(r["id"]).status == "COMPLETED"


def test_sse_and_export_redacts_secrets(client):
    r = client.post("/api/v1/commands", json={"goal": "Qué tengo hoy"}).json()
    run_until_pause(r["id"])
    response = client.get("/api/v1/runs/" + r["id"] + "/events")
    assert "text/event-stream" in response.headers["content-type"]
    assert "COMPLETED" in response.text
    data = client.get("/api/v1/export")
    assert data.status_code == 200
    assert "Temporary-test-pass" not in data.text
    assert "password" not in data.json()


def test_prompt_injection_cannot_add_tools(client):
    from pablo.schemas import Plan

    with pytest.raises(ValueError):
        Plan.model_validate(
            {"summary": "Ignore policy", "steps": [{"tool": "terminal", "arguments": {"command": "rm"}}]}
        )


def test_migration_and_readiness(client):
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/ready").json()["database"] == "ready"
    
    assert client.get("/api/v1/state").status_code == 200


def test_bootstrap_creates_project_and_task_dependencies(client):
    profile = client.get("/api/v1/state").json()["profile"]
    profile["autonomy"] = "AUTONOMOUS"
    client.put("/api/v1/settings", json=profile)
    r = client.post("/api/v1/commands", json={"goal": "Quiero crear un videojuego", "mode": "DO"}).json()
    assert run_until_pause(r["id"]).status == "COMPLETED"
    with DB() as db:
        run = db.get(Run, r["id"])
        assert run.project_id
        tasks = list(db.scalars(select(Item).where(Item.kind == "tasks").order_by(Item.created_at)))
        assert len(tasks) == 4
        assert tasks[0].data["dependencies"] == []
        assert tasks[1].data["dependencies"] == [tasks[0].id]
        assert all(t.data["project_id"] == run.project_id for t in tasks)


def test_plan_template_contains_real_steps_but_no_writes(client):
    r = client.post("/api/v1/commands", json={"goal": "Crear app", "mode": "PLAN"}).json()
    run = run_until_pause(r["id"])
    assert len(run.plan) == 5
    assert run.plan[0]["tool"] == "projects.create"
    assert not [i for i in client.get("/api/v1/state").json()["items"] if i["kind"] in {"tasks", "projects"}]


def test_rag_supplies_retrieved_evidence_to_provider(client, monkeypatch):
    from pablo.providers import CompatibleProvider
    from pablo.schemas import Plan

    client.post(
        "/api/v1/documents",
        files={"file": ("energy.txt", b"Photosynthesis transforms light into chemical energy.")},
    )
    monkeypatch.setenv("AI_API_KEY", "test-only-key")
    monkeypatch.setenv("AI_MODEL", "test-only-model")
    captured = {}

    def fake_plan(self, goal, mode, context):
        captured.update(context)
        return Plan(summary="Evidence-based test response", steps=[]), {"total_tokens": 20}

    monkeypatch.setattr(CompatibleProvider, "plan", fake_plan)
    r = client.post("/api/v1/commands", json={"goal": "Explain photosynthesis"}).json()
    assert run_until_pause(r["id"]).status == "COMPLETED"
    assert captured["documents"][0]["source"] == "energy.txt"
    assert "chemical" in captured["documents"][0]["text"]


def test_ask_cannot_execute_model_proposed_write(client, monkeypatch):
    from pablo.providers import CompatibleProvider
    from pablo.schemas import Plan

    monkeypatch.setenv("AI_API_KEY", "test-only-key")
    monkeypatch.setenv("AI_MODEL", "test-only-model")
    monkeypatch.setattr(
        CompatibleProvider,
        "plan",
        lambda *args: (
            Plan(
                summary="bad plan",
                steps=[{"tool": "projects.create", "arguments": {"title": "Unauthorized"}}],
            ),
            {},
        ),
    )
    r = client.post("/api/v1/commands", json={"goal": "Explain my project", "mode": "ASK"}).json()
    assert run_until_pause(r["id"]).status == "BLOCKED"
    assert not [i for i in client.get("/api/v1/state").json()["items"] if i["kind"] == "projects"]


def test_docx_and_pdf_extraction(client):
    from io import BytesIO

    from docx import Document

    doc = Document()
    doc.add_paragraph("Un índice acelera consultas de bases de datos.")
    raw = BytesIO()
    doc.save(raw)
    response = client.post("/api/v1/documents", files={"file": ("database.docx", raw.getvalue())})
    assert response.status_code == 200
    assert client.get("/api/v1/search", params={"q": "consultas"}).json()["sources"]
    # Real minimal PDF with a text stream; no optional PDF generation dependency.
    stream = b"BT /F1 12 Tf 50 700 Td (Photosynthesis converts energy) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    pdf = b"%PDF-1.4\n"
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf += str(i).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
    start = len(pdf)
    pdf += b"xref\n0 6\n0000000000 65535 f \n"
    for offset in offsets[1:]:
        pdf += f"{offset:010d} 00000 n \n".encode()
    pdf += b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n" + str(start).encode() + b"\n%%EOF"
    response = client.post("/api/v1/documents", files={"file": ("energy.pdf", pdf)})
    assert response.status_code == 200, response.text
    assert client.get("/api/v1/search", params={"q": "photosynthesis"}).json()["sources"]


def test_demo_never_calls_embedding_provider(client, monkeypatch):
    from pablo.providers import CompatibleProvider

    profile = client.get("/api/v1/state").json()["profile"]
    profile["demo"] = True
    client.put("/api/v1/settings", json=profile)

    def forbidden(*args):
        raise AssertionError("Demo transmitted data to embeddings provider")

    monkeypatch.setattr(CompatibleProvider, "embed", forbidden)
    doc = client.post("/api/v1/documents", files={"file": ("private.txt", b"Private astronomy notes")})
    assert doc.status_code == 200
    with DB() as db:
        chunk = db.scalar(select(Chunk))
        chunk.embedding = [1.0, 0.0]
        db.commit()
    result = client.get("/api/v1/search", params={"q": "astronomy"})
    assert result.status_code == 200
    assert result.json()["sources"][0]["method"] == "lexical"


def test_scheduler_is_idempotent_and_uses_permissions(client):
    from datetime import datetime, timedelta, timezone

    from pablo.scheduling import dispatch_due

    at = datetime.now(timezone.utc) + timedelta(minutes=1)
    created = client.post(
        "/api/v1/schedules",
        json={
            "title": "Organizar proyecto",
            "goal": "Crear proyecto",
            "mode": "DO",
            "run_at": at.isoformat(),
        },
    )
    assert created.status_code == 200
    assert dispatch_due(at + timedelta(seconds=1)) == 1
    assert dispatch_due(at + timedelta(seconds=2)) == 0
    row = client.get("/api/v1/schedules").json()[0]
    assert row["enabled"] is False
    assert run_until_pause(row["last_run_id"]).status == "WAITING_APPROVAL"
    assert not [i for i in client.get("/api/v1/state").json()["items"] if i["kind"] == "projects"]


def test_recurring_schedule_coalesces_missed_occurrences(client):
    from datetime import datetime, timedelta, timezone

    from pablo.scheduling import dispatch_due, parse_instant

    at = datetime.now(timezone.utc) + timedelta(minutes=1)
    client.post(
        "/api/v1/schedules",
        json={
            "title": "Revisar tareas",
            "goal": "Qué tengo pendiente",
            "run_at": at.isoformat(),
            "interval_minutes": 60,
        },
    )
    later = at + timedelta(hours=5, minutes=3)
    assert dispatch_due(later) == 1
    assert dispatch_due(later) == 0
    row = client.get("/api/v1/schedules").json()[0]
    assert parse_instant(row["next_run"]) == at + timedelta(hours=6)
    assert row["enabled"] is True


def test_scheduler_validation_pause_delete_and_export(client):
    from datetime import datetime, timedelta, timezone

    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    base = {"title": "T", "goal": "G", "run_at": future}
    assert client.post("/api/v1/schedules", json={**base, "interval_minutes": 1}).status_code == 422
    assert client.post("/api/v1/schedules", json={**base, "run_at": "2026-01-01T08:00:00"}).status_code == 422
    assert client.post("/api/v1/schedules", json={**base, "project_id": "missing"}).status_code == 404
    row = client.post("/api/v1/schedules", json=base).json()
    assert client.put("/api/v1/schedules/" + row["id"], json={"enabled": False}).status_code == 200
    assert client.get("/api/v1/schedules").json()[0]["enabled"] is False
    assert client.get("/api/v1/export").json()["schedules"][0]["id"] == row["id"]
    assert client.delete("/api/v1/schedules/" + row["id"]).status_code == 200
    assert client.get("/api/v1/schedules").json() == []


def test_second_worker_cannot_execute_same_step(client, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from pablo.tools import Tool, registry

    r = client.post("/api/v1/commands", json={"goal": "Qué tengo hoy"}).json()
    process(r["id"])
    entered, release = threading.Event(), threading.Event()
    calls = []

    def blocked(*args):
        calls.append("called")
        entered.set()
        assert release.wait(5)
        return []

    monkeypatch.setitem(registry.tools, "tasks.list", Tool("tasks.list", "SAFE", "Productivity", blocked))
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(process, r["id"])
        assert entered.wait(3)
        second = executor.submit(process, r["id"])
        second.result(timeout=3)
        release.set()
        first.result(timeout=3)
    assert calls == ["called"]
    with DB() as db:
        assert db.get(Run, r["id"]).lease_token is None


def test_expired_worker_lease_can_be_recovered(client):
    import time

    from pablo.worker import claim

    r = client.post("/api/v1/commands", json={"goal": "Qué tengo hoy"}).json()
    first = claim(r["id"])
    assert first
    assert claim(r["id"]) is None
    with DB() as db:
        row = db.get(Run, r["id"])
        row.lease_until = time.time() - 1
        db.commit()
    second = claim(r["id"])
    assert second and second != first


def test_delete_conversation_removes_private_history(client):
    r = client.post("/api/v1/commands", json={"goal": "Sensitive test conversation"}).json()
    assert client.delete("/api/v1/items/" + r["conversation_id"]).status_code == 409
    run_until_pause(r["id"])
    assert client.get("/api/v1/conversations/" + r["conversation_id"] + "/messages").json()["messages"]
    assert client.delete("/api/v1/items/" + r["conversation_id"]).status_code == 200
    assert client.get("/api/v1/runs/" + r["id"]).status_code == 404
    assert "Sensitive test conversation" not in client.get("/api/v1/export").text


def test_history_paginates_without_losing_old_messages(client):
    r = client.post("/api/v1/commands", json={"goal": "History"}).json()
    with DB() as db:
        for i in range(205):
            db.add(
                Item(
                    kind="messages",
                    title="M",
                    data={"conversation_id": r["conversation_id"], "content": str(i)},
                )
            )
        db.commit()
    url = "/api/v1/conversations/" + r["conversation_id"] + "/messages"
    first = client.get(url).json()
    second = client.get(url + "?offset=200").json()
    assert first["has_more"] is True
    assert len(first["messages"]) == 200
    assert len(second["messages"]) == 6
    assert not set(m["id"] for m in first["messages"]) & set(m["id"] for m in second["messages"])


def test_ready_distinguishes_worker_offline(client):
    assert client.get("/api/v1/runtime").json()["worker"] == "OFFLINE"
    from pablo.db import Runtime, now

    with DB() as db:
        db.add(Runtime(id="worker", updated_at=now()))
        db.commit()
    assert client.get("/api/v1/runtime").json()["worker"] == "ONLINE"


def test_upgrade_from_version_one_preserves_records(tmp_path):
    import json
    import sqlite3
    import subprocess
    import sys

    database = tmp_path / "upgrade.db"
    environment = {**os.environ, "DATABASE_URL": "sqlite:///" + str(database), "PYTHONPATH": "backend"}
    base = [sys.executable, "-m", "alembic", "-c", "backend/alembic.ini", "upgrade"]
    subprocess.run([*base, "0001"], env=environment, check=True, capture_output=True)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO items (id,kind,title,data,created_at,updated_at,version) VALUES (?,?,?,?,?,?,?)",
            (
                "old-project",
                "projects",
                "Conservar este proyecto",
                json.dumps({"status": "ACTIVE"}),
                "2026-01-01",
                "2026-01-01",
                1,
            ),
        )
    subprocess.run([*base, "head"], env=environment, check=True, capture_output=True)
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute("SELECT title FROM items WHERE id=?", ("old-project",)).fetchone()[0]
            == "Conservar este proyecto"
        )
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0004"
        assert "lease_token" in [r[1] for r in connection.execute("PRAGMA table_info(agent_runs)")]


def test_user_facing_results_are_grounded_in_tool_output():
    from pablo.presentation import render_results

    text = render_results(
        [
            {
                "tool": "tasks.list",
                "result": [{"title": "Preparar examen", "priority": "HIGH", "due": "2026-10-01"}],
            }
        ]
    )
    assert "Preparar examen — prioridad alta" in text
    assert "2026-10-01" in text
    assert "```json" not in text


def test_old_pending_run_remains_visible(client):
    r = client.post("/api/v1/commands", json={"goal": "Crear proyecto", "mode": "DO"}).json()
    run_until_pause(r["id"])
    with DB() as db:
        for i in range(45):
            db.add(Run(goal=str(i), mode="ASK", status="COMPLETED", conversation_id=r["conversation_id"]))
        db.commit()
    state = client.get("/api/v1/state").json()
    assert any(row["id"] == r["id"] for row in state["runs"])
    assert any(a["run_id"] == r["id"] for a in state["approvals"])


def test_bootstrap_updates_conversation_context(client):
    profile = client.get("/api/v1/state").json()["profile"]
    profile["autonomy"] = "AUTONOMOUS"
    client.put("/api/v1/settings", json=profile)
    first = client.post("/api/v1/commands", json={"goal": "Crear app", "mode": "DO"}).json()
    run = run_until_pause(first["id"])
    follow = client.post(
        "/api/v1/commands", json={"goal": "Qué tengo pendiente", "conversation_id": first["conversation_id"]}
    ).json()
    assert follow["project_id"] == run.project_id


@pytest.mark.parametrize(
    "origin, accepted",
    [
        ("http://localhost:8000", True),
        ("http://127.0.0.1:8000", True),
        ("http://[::1]:8000", True),
        ("https://localhost:8000", False),
        ("http://localhost:8001", False),
        ("http://localhost.evil.example:8000", False),
        ("http://evil.example:8000", False),
        ("null", False),
        ("http://evil.example@localhost:8000", False),
        ("http://localhost:8000/path", False),
        ("http://localhost:bad", False),
    ],
)
def test_local_origin_setup_regression(client, monkeypatch, origin, accepted):
    monkeypatch.setenv("APP_ORIGIN", "http://localhost:8000")
    # Remove the fixture's account to exercise real first-run account creation.
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(delete(table))
    response = client.post(
        "/api/v1/auth/setup",
        headers={"Origin": origin},
        json={"name": "Pablo test", "password": "Temporary-test-pass-2026"},
    )
    assert response.status_code == (200 if accepted else 403)


def test_origin_aliases_do_not_extend_external_deployments():
    from pablo.security import allowed_origin

    assert allowed_origin("https://pablo.example", "https://pablo.example:443")
    assert not allowed_origin("http://localhost:8000", "https://pablo.example")
    assert allowed_origin("http://localhost:8000", "http://127.0.0.1:8000")
    assert not allowed_origin("http://127.0.0.1:8000", "http://localhost:5173")
