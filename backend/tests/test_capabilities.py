"""Integration tests against disposable data; no production account is touched."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from test_flows import run_until_pause

from pablo.configuration import reserve_request, settle_request
from pablo.db import DB, BudgetPeriod, Run
from pablo.tools import Tool, registry
from pablo.worker import process
from pablo.workspace_tools import code_run, code_scaffold, workspace_read, workspace_write


def test_calendar_tools_and_crud_share_storage(client):
    body = {"title": "Revisión", "start": "2026-12-01T09:00:00+01:00", "end": "2026-12-01T10:00:00+01:00"}
    item = client.post("/api/v1/calendar", json=body)
    assert item.status_code == 200
    run = client.post("/api/v1/tool-runs", json={"tool": "calendar.list"}).json()
    assert run_until_pause(run["id"]).status == "COMPLETED"
    with DB() as db:
        assert db.get(Run, run["id"]).plan[0]["result"]["events"][0]["title"] == "Revisión"
    assert client.patch("/api/v1/calendar/" + item.json()["id"], json=body | {"title": "Editado"}).status_code == 200
    assert client.post("/api/v1/calendar", json=body | {"end": body["start"]}).status_code == 422
    assert client.delete("/api/v1/calendar/" + item.json()["id"]).status_code == 200
    assert client.get("/api/v1/calendar").json() == []


def test_all_specialists_operational_and_critical_requires_approval(client, monkeypatch):
    assert all(agent["tools"] for agent in client.get("/api/v1/agents").json())
    profile = client.get("/api/v1/state").json()["profile"]
    client.put("/api/v1/settings", json=profile | {"autonomy": "AUTONOMOUS"})
    called = []
    monkeypatch.setitem(registry.tools, "email.send", Tool("email.send", "CRITICAL", "Email", lambda *a: called.append(True) or {"sent": True}))
    run = client.post("/api/v1/tool-runs", json={"tool": "email.send", "arguments": {"to": "test@example.invalid"}}).json()
    assert run_until_pause(run["id"]).status == "WAITING_APPROVAL"
    assert called == []
    approval = client.get("/api/v1/state").json()["approvals"][0]
    client.post("/api/v1/approvals/" + approval["id"], json={"approve": True})
    assert run_until_pause(run["id"]).status == "COMPLETED"
    process(run["id"])
    assert called == [True]


def test_ambiguous_external_write_cannot_replay(client, monkeypatch):
    def fail(*args):
        raise ValueError("Simulated lost response")
    monkeypatch.setitem(registry.tools, "email.send", Tool("email.send", "CRITICAL", "Email", fail))
    run = client.post("/api/v1/tool-runs", json={"tool": "email.send"}).json()
    run_until_pause(run["id"])
    approval = client.get("/api/v1/state").json()["approvals"][0]
    client.post("/api/v1/approvals/" + approval["id"], json={"approve": True})
    assert run_until_pause(run["id"]).status == "FAILED"
    assert client.post("/api/v1/runs/" + run["id"] + "/retry").status_code == 409


def test_provider_secret_hidden_and_persistent(client, monkeypatch):
    monkeypatch.setenv("PABLO_SECRET_KEY", Fernet.generate_key().decode())
    body = {"model": "test-model", "api_key": "private-test-key", "monthly_budget_usd": 10,
            "input_cost_per_million": 1, "output_cost_per_million": 2}
    result = client.put("/api/v1/provider", json=body)
    assert result.status_code == 200, result.text
    assert result.json()["key_present"] is True
    for path in ["provider", "state", "export", "integrations"]:
        assert "private-test-key" not in client.get("/api/v1/" + path).text
    assert client.put("/api/v1/provider", json={"model": "updated"}).json()["key_present"] is True
    assert client.put("/api/v1/provider", json={"base_url": "http://insecure.example/v1"}).status_code == 422


def test_budget_reservation_is_atomic(client):
    config = {"monthly_budget_usd": .012, "input_cost_per_million": 1, "output_cost_per_million": 1}
    payload = {"max_completion_tokens": 1000}
    def reserve(_):
        try:
            return reserve_request(config, payload)
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=4) as executor:
        outcomes = list(executor.map(reserve, range(4)))
    accepted = [item for item in outcomes if item]
    assert len(accepted) == 2
    with DB() as db:
        assert db.scalar(select(BudgetPeriod)).committed_micro <= 12000
    settle_request(config, accepted[0], {"prompt_tokens": 100, "completion_tokens": 100})
    with DB() as db:
        assert db.scalar(select(BudgetPeriod)).actual_micro == 200


@pytest.mark.parametrize("path", ["../outside.txt", "C:\\private.txt", ".env", "dir/.git/config", "file.txt:secret", "NUL.txt", "dir/.. /x", "/etc/passwd"])
def test_workspace_rejects_escapes(tmp_path, monkeypatch, path):
    monkeypatch.setenv("PABLO_WORKSPACE_ROOT", str(tmp_path))
    with pytest.raises(ValueError):
        workspace_write(None, {"path": path, "content": "test"}, None)


def test_workspace_create_read_and_real_code_run(tmp_path, monkeypatch):
    monkeypatch.setenv("PABLO_WORKSPACE_ROOT", str(tmp_path))
    assert workspace_write(None, {"path": "demo.py", "content": "print(6 * 7)"}, None)["verified"]
    assert "print" in workspace_read(None, {"path": "demo.py"}, None)["content"]
    result = code_run(None, {"path": "demo.py", "runner": "python"}, None)
    assert result["verified"] and result["output"].strip() == "42"
    with pytest.raises(ValueError):
        workspace_write(None, {"path": "demo.py", "content": "replaced"}, None)
    workspace_write(None, {"path": "loop.py", "content": "while True: pass"}, None)
    assert code_run(None, {"path": "loop.py", "runner": "python", "timeout_seconds": 1}, None)["timed_out"]


def test_scaffold_game_is_real_and_cannot_overwrite(tmp_path, monkeypatch):
    monkeypatch.setenv("PABLO_WORKSPACE_ROOT", str(tmp_path))
    result = code_scaffold(None, {"name": "Estrellas", "kind": "game"}, None)
    assert result["verified"]
    assert 'src="script.js"' in next(tmp_path.rglob("index.html")).read_text(encoding="utf-8")
    assert "requestAnimationFrame" in next(tmp_path.rglob("script.js")).read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        code_scaffold(None, {"name": "Estrellas", "kind": "game"}, None)


def test_backup_merge_and_reindex_keep_documents(client):
    doc = client.post("/api/v1/documents", files={"file": ("source.md", ("evidence " * 500).encode())}).json()
    assert client.post("/api/v1/documents/" + doc["id"] + "/reindex").status_code == 200
    exported = client.get("/api/v1/export").json()
    imported = client.post("/api/v1/import", json=exported)
    assert imported.status_code == 200, imported.text
    docs = [row for row in client.get("/api/v1/state").json()["items"] if row["kind"] == "documents"]
    assert len(docs) == 2
    assert len({row["id"] for row in docs}) == 2
    assert client.get("/api/v1/search?q=evidence").json()["sources"]


def test_delete_account_requires_password_and_preserves_no_credentials(client, monkeypatch):
    monkeypatch.setenv("PABLO_SECRET_KEY", Fernet.generate_key().decode())
    client.put("/api/v1/provider", json={"model": "test", "api_key": "erase-test-key"})
    assert client.request("DELETE", "/api/v1/account", json={"password": "wrong", "confirmation": "ELIMINAR MI CUENTA"}).status_code == 403
    response = client.request("DELETE", "/api/v1/account", json={"password": "Temporary-test-pass-2026", "confirmation": "ELIMINAR MI CUENTA"})
    assert response.status_code == 200
    assert client.get("/api/v1/state").status_code == 401
    assert client.get("/api/v1/auth/status").json()["setup_required"]
