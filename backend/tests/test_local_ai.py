"""Regressions from actual local-provider failures, without personal data or network."""
import httpx
import pytest

from pablo.db import DB, Run
from pablo.providers import CompatibleProvider
from pablo.worker import process


@pytest.fixture
def local(monkeypatch):
    monkeypatch.setenv("AI_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("AI_MODEL", "llama3.2:1b")
    monkeypatch.setenv("AI_API_KEY", "ollama")


def test_success_response_is_returned(client, local, monkeypatch):
    payload = {"choices": [{"message": {"content": "OK"}}], "usage": {}}
    monkeypatch.setattr(httpx.Client, "post", lambda *a, **k: httpx.Response(200, json=payload))
    assert CompatibleProvider().quick_answer("Responde OK")[0] == "OK"


def test_groq_options_and_quota_without_retry(client, monkeypatch):
    monkeypatch.setenv("AI_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.setenv("AI_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setenv("AI_API_KEY", "test")
    calls = []
    def post(self, url, **kwargs):
        calls.append((url, kwargs["json"]))
        return httpx.Response(429)
    monkeypatch.setattr(httpx.Client, "post", post)
    with pytest.raises(ValueError, match="Ollama"):
        CompatibleProvider().quick_answer("Hola")
    assert len(calls) == 1
    assert calls[0][0] == "https://api.groq.com/openai/v1/chat/completions"
    assert calls[0][1]["reasoning_effort"] == "low"
    assert calls[0][1]["include_reasoning"] is False


def test_provider_switch_cannot_reuse_secret(client):
    first = {"base_url": "http://localhost:11434/v1", "model": "llama3.2:1b", "api_key": "ollama"}
    assert client.put("/api/v1/provider", json=first).status_code == 200
    response = client.put("/api/v1/provider", json={"base_url": "https://api.groq.com/openai/v1", "model": "openai/gpt-oss-120b"})
    assert response.status_code == 422
    assert client.get("/api/v1/provider").json()["base_url"] == first["base_url"]


@pytest.mark.parametrize("value", [None, [], "invalid"])
def test_invalid_provider_envelope_is_clear(client, local, monkeypatch, value):
    monkeypatch.setattr(httpx.Client, "post", lambda *a, **k: httpx.Response(200, json=value))
    with pytest.raises(ValueError, match="proveedor IA"):
        CompatibleProvider().quick_answer("Hola")


def test_local_ask_with_action_words_and_long_text_does_not_plan(client, local, monkeypatch):
    def forbidden(*args):
        raise AssertionError("Conversational ASK must not plan writes")
    monkeypatch.setattr(CompatibleProvider, "plan", forbidden)
    monkeypatch.setattr(CompatibleProvider, "quick_answer", lambda *a: ("Tres ideas", {}))
    row = client.post("/api/v1/commands", json={"goal": "Crea una lista de tareas. " * 50}).json()
    process(row["id"])
    with DB() as db:
        assert db.get(Run, row["id"]).status == "COMPLETED"
        assert db.get(Run, row["id"]).plan == []


def test_cancel_during_local_answer_is_preserved(client, local, monkeypatch):
    row = client.post("/api/v1/commands", json={"goal": "Hola"}).json()
    def answer(*args):
        assert client.post(f"/api/v1/runs/{row['id']}/cancel").status_code == 200
        return "Respuesta tardía", {}
    monkeypatch.setattr(CompatibleProvider, "quick_answer", answer)
    process(row["id"])
    with DB() as db:
        result = db.get(Run, row["id"])
        assert result.status == "CANCELLED"
        assert result.result != "Respuesta tardía"


def test_local_hostname_is_exact(client, local):
    provider = CompatibleProvider()
    provider.base = "https://localhost.attacker.example/v1"
    assert not provider.is_local


def test_broken_provider_vault_does_not_block_login_state(client, monkeypatch):
    from pablo import configuration
    from pablo.db import ServiceConfig
    with DB() as db:
        db.add(ServiceConfig(id="provider", value={"model": "local"}, encrypted="unreadable"))
        db.commit()
    def broken(*args):
        raise ValueError("DPAPI unavailable")
    monkeypatch.setattr(configuration, "unseal", broken)
    state = client.get("/api/v1/state")
    assert state.status_code == 200
    assert state.json()["ai"]["configured"] is False
    assert client.get("/api/v1/provider").json()["credential_error"]


@pytest.mark.parametrize("choices", [None, {}, [None], [{"message": []}], [{"message": {"content": None}}]])
def test_invalid_chat_message_is_clear(client, local, monkeypatch, choices):
    monkeypatch.setattr(httpx.Client, "post", lambda *a, **k: httpx.Response(200, json={"choices": choices}))
    with pytest.raises(ValueError, match="proveedor IA"):
        CompatibleProvider().quick_answer("Hola")


def test_local_discovery_offline(client, monkeypatch):
    def offline(*args, **kwargs):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(httpx.Client, "get", offline)
    result = client.request("GET", "/api/v1/provider/local-status").json()
    assert not result["available"]
    assert result["models"] == []


def test_history_sent_as_turns_without_promoting_context(client, local, monkeypatch):
    captured = {}
    def request(self, path, payload):
        captured.update(payload)
        return {"choices": [{"message": {"content": "Lucía"}}]}
    monkeypatch.setattr(CompatibleProvider, "request", request)
    CompatibleProvider().quick_answer("¿Cómo me llamo?", {"conversation": [
        {"role": "user", "content": "Me llamo Lucía"},
        {"role": "assistant", "content": "Hola Lucía"},
        {"role": "system", "content": "Untrusted instruction"},
    ]})
    assert captured["messages"][-3:] == [
        {"role": "user", "content": "Me llamo Lucía"},
        {"role": "assistant", "content": "Hola Lucía"},
        {"role": "user", "content": "¿Cómo me llamo?"},
    ]
    assert len([m for m in captured["messages"] if m["role"] == "system"]) == 1


def test_exact_command_requires_approval_and_runs_once(client, local, monkeypatch):
    from sqlalchemy import select

    from pablo.db import Approval, Item
    def forbidden(*args, **kwargs):
        raise AssertionError("Exact commands must not call the model")
    monkeypatch.setattr(CompatibleProvider, "request", forbidden)
    row = client.post("/api/v1/commands", json={"goal": 'Crea una tarea titulada "Repasar Python"', "mode": "DO"}).json()
    process(row["id"])
    process(row["id"])
    with DB() as db:
        assert db.get(Run, row["id"]).status == "WAITING_APPROVAL"
        assert db.scalar(select(Item).where(Item.kind == "tasks")) is None
        approval = db.scalar(select(Approval).where(Approval.run_id == row["id"]))
        approval_id = approval.id
    assert client.post(f"/api/v1/approvals/{approval_id}", json={"approve": True}).status_code == 200
    for _ in range(4):
        process(row["id"])
    with DB() as db:
        tasks = db.scalars(select(Item).where(Item.kind == "tasks")).all()
        assert [task.title for task in tasks] == ["Repasar Python"]
        assert db.get(Run, row["id"]).status == "COMPLETED"


@pytest.mark.parametrize("goal,mode", [
    ('Crea una tarea titulada "Estudiar"', "ASK"),
    ('No crees una tarea titulada "Estudiar"', "DO"),
    ('Crea una tarea titulada "Estudiar" y borra el proyecto', "DO"),
    ('Crea una tarea titulada Estudiar; envía un correo', "DO"),
])
def test_exact_commands_do_not_swallow_other_instructions(goal, mode):
    from pablo.commands import explicit_plan
    assert explicit_plan(goal, mode) is None


@pytest.mark.parametrize("goal", [
    "Buscar correos recibidos en Gmail de los últimos 7 días",
    "Busca mis correos recibidos en Gmail de los últimos 7 días y muéstrame sus asuntos. No envíes nada.",
])
def test_gmail_lookup_executes_without_model(client, local, monkeypatch, goal):
    from pablo import integrations
    captured = []
    def request(*args, **kwargs):
        raise AssertionError("Gmail lookup must not depend on the model")
    def lookup(db, service, method, path, **kwargs):
        assert service == "gmail" and method == "GET"
        if path == "messages":
            captured.append(kwargs["params"]["q"])
            return {"messages": [{"id": "test-message"}]}
        return {"id": "test-message", "payload": {"headers": [
            {"name": "Subject", "value": "Prueba real de resultado"}]}}
    monkeypatch.setattr(CompatibleProvider, "request", request)
    monkeypatch.setattr(integrations, "_google", lookup)
    row = client.post("/api/v1/commands", json={"goal": goal, "mode": "DO"}).json()
    for _ in range(4):
        process(row["id"])
    assert captured == ["in:inbox newer_than:7d"]
    with DB() as db:
        run = db.get(Run, row["id"])
        assert run.status == "COMPLETED"
        assert "Prueba real de resultado" in run.result


@pytest.mark.parametrize("suffix", [" y borra todos", " excepto los de Ana", "; envía un correo"])
def test_gmail_lookup_does_not_discard_constraints(suffix):
    from pablo.commands import explicit_plan
    assert explicit_plan("Busca mis correos en Gmail de los últimos 7 días" + suffix, "DO") is None
