import copy

import httpx
import pytest

from pablo.providers import CompatibleProvider


@pytest.fixture
def groq(client, monkeypatch):
    monkeypatch.setenv("AI_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.setenv("AI_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setenv("AI_API_KEY", "test")


def test_generated_json_400_recovers_before_actions(groq, monkeypatch):
    calls = []
    def post(self, url, **kwargs):
        calls.append(copy.deepcopy(kwargs["json"]))
        if len(calls) == 1:
            return httpx.Response(400, json={"error": {"code": "json_validate_failed"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"summary":"Guardaré los deberes", "steps":[{"tool":"tasks.create","arguments":{"title":"Leer tema 3"},"depends_on":[]}]}'}}]})
    monkeypatch.setattr(httpx.Client, "post", post)
    plan, _ = CompatibleProvider().plan("Tengo deberes: leer el tema 3. Apúntalos", "CHAT", {})
    assert plan.steps[0].arguments["title"] == "Leer tema 3"
    assert len(calls) == 2
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in calls[1]
    assert calls[0]["messages"] == calls[1]["messages"]
    import json
    from datetime import date
    context = json.loads(calls[0]["messages"][1]["content"])["CONTEXTO_NO_CONFIABLE"]
    assert len(context["fechas_verificadas"]) == 14
    weekdays = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
    for row in context["fechas_verificadas"]:
        assert row["weekday"] == weekdays[date.fromisoformat(row["date"]).weekday()]


def test_json_recovery_does_not_retry_indefinitely(groq, monkeypatch):
    calls = []
    def post(*args, **kwargs):
        calls.append(kwargs["json"])
        return httpx.Response(400, json={"error": {"code": "json_validate_failed"}})
    monkeypatch.setattr(httpx.Client, "post", post)
    with pytest.raises(ValueError, match="No se han aplicado cambios"):
        CompatibleProvider().plan("Hola", "CHAT", {})
    assert len(calls) == 2


@pytest.mark.parametrize("status,body", [(400, {"error": {"code": "invalid_parameter", "message": "secret must not leak"}}), (401, {}), (429, {})])
def test_other_provider_errors_are_not_retried_or_exposed(groq, monkeypatch, status, body):
    calls = []
    def post(*args, **kwargs):
        calls.append(kwargs["json"])
        return httpx.Response(status, json=body)
    monkeypatch.setattr(httpx.Client, "post", post)
    with pytest.raises(ValueError) as error:
        CompatibleProvider().plan("Hola", "CHAT", {})
    assert "secret" not in str(error.value)
    assert len(calls) == 1


def test_recovered_json_still_rejects_retired_tools(groq, monkeypatch):
    calls = []
    def post(*args, **kwargs):
        calls.append(kwargs["json"])
        if len(calls) == 1:
            return httpx.Response(400, json={"error": {"code": "json_validate_failed"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"summary":"Consulta", "steps":[{"tool":"calendar.list","arguments":{},"depends_on":[]}]}'}}]})
    monkeypatch.setattr(httpx.Client, "post", post)
    with pytest.raises(ValueError, match="ya no está disponible"):
        CompatibleProvider().plan("Hola", "CHAT", {})
    assert len(calls) == 2
