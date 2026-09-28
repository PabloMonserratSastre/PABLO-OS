"""Connector regression tests use mocked transports: no mail or remote changes are sent."""

import base64
import json
import time
from email import policy
from email.parser import BytesParser
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pablo import integrations as module
from pablo import security
from pablo.db import Base, Session


@pytest.fixture
def database(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(module, "DB", factory)
    monkeypatch.setattr(security, "DB", factory)
    monkeypatch.setenv("PABLO_SECRET_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("APP_ORIGIN", "http://testserver")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    for provider in module.ENV.values():
        for env in provider.values():
            monkeypatch.delenv(env, raising=False)
    with factory() as db:
        yield db
    engine.dispose()


@pytest.fixture
def api(database):
    app = FastAPI()
    app.include_router(module.router)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    database.add(Session(id=security.digest("test-session"), expires=int(time.time()) + 3600))
    database.commit()
    with TestClient(app) as client:
        client.cookies.set("pablo_session", "test-session")
        yield client


@pytest.fixture
def remote(monkeypatch):
    original = httpx.Client
    requests = []

    def install(handler):
        def capture(request):
            requests.append(request)
            return handler(request)

        def client(**kwargs):
            assert kwargs["follow_redirects"] is False
            assert kwargs["trust_env"] is False
            return original(transport=httpx.MockTransport(capture), **kwargs)

        monkeypatch.setattr(module.httpx, "Client", client)
        return requests

    return install


def google_credentials(database, *, expired=False, scopes=None):
    module._store(database, "google", {
        "client_secret": "secret-123", "access_token": "access-old", "refresh_token": "refresh-private",
        "expires_at": time.time() - 10 if expired else time.time() + 3600,
        "scopes": scopes if scopes is not None else [s for group in module.SCOPES.values() for s in group],
    }, {"client_id": "client-123"})
    database.commit()


def test_cipher_roundtrip_tampering_and_wrong_key(database, monkeypatch):
    text = module.seal({"token": "super-private-credential"})
    assert "super-private" not in text
    assert module.unseal(text)["token"] == "super-private-credential"
    with pytest.raises(ValueError, match="descifrar"):
        module.unseal(text[:-5] + "ABCDE")
    monkeypatch.setenv("PABLO_SECRET_KEY", Fernet.generate_key().decode())
    with pytest.raises(ValueError, match="descifrar"):
        module.unseal(text)


def test_configuration_authentication_secret_hiding_and_disconnect(api, database):
    api.cookies.clear()
    assert api.put("/api/v1/integrations/github", json={"secrets": {"token": "private-token"}}).status_code == 401
    api.cookies.set("pablo_session", "test-session")
    response = api.put("/api/v1/integrations/github", json={"secrets": {"token": "private-token"}})
    assert response.status_code == 200
    assert "private-token" not in response.text
    database.expire_all()
    row = database.get(module.Integration, "github")
    assert "private-token" not in row.encrypted
    status = module.integration_status(database)
    assert "private-token" not in json.dumps(status)
    assert next(p for p in status if p["id"] == "github")["status"] == "CONFIGURED"
    assert api.put("/api/v1/integrations/github", json={"config": {"token": "oops"}}).status_code == 422
    assert api.delete("/api/v1/integrations/github").status_code == 200
    database.expire_all()
    assert module.credentials(database, "github") == {}


def test_disconnect_disables_environment_credentials(api, database, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "environment-token")
    assert module.credentials(database, "github")["token"] == "environment-token"
    assert api.delete("/api/v1/integrations/github").status_code == 200
    database.expire_all()
    assert module.credentials(database, "github") == {}


def test_google_oauth_pkce_callback_and_replay(api, database, remote):
    assert api.put("/api/v1/integrations/google", json={"config": {"client_id": "client-123"}, "secrets": {"client_secret": "secret-123"}}).status_code == 200
    response = api.post("/api/v1/integrations/google/authorize", json={"services": ["calendar"]})
    assert response.status_code == 200
    params = parse_qs(urlsplit(response.json()["url"]).query)
    assert params["code_challenge_method"] == ["S256"]
    assert params["scope"] == [module.SCOPES["calendar"][0]]
    assert "client_secret" not in params
    state = params["state"][0]
    stored = database.get(module.OAuthState, security.digest(state))
    assert stored and "verifier" not in stored.encrypted
    pending = module.unseal(stored.encrypted)
    challenge = base64.urlsafe_b64encode(module.hashlib.sha256(pending["verifier"].encode()).digest()).decode().rstrip("=")
    assert params["code_challenge"] == [challenge]
    requests = remote(lambda request: httpx.Response(200, json={"access_token": "new-token", "refresh_token": "new-refresh", "expires_in": 3600}))
    callback = api.get("/api/v1/integrations/google/callback", params={"state": state, "code": "valid-code"}, follow_redirects=False)
    assert callback.status_code == 303
    assert callback.headers["location"] == "/?integration=google&connected=1"
    form = parse_qs(requests[0].content.decode())
    assert form["code_verifier"] == [pending["verifier"]]
    assert api.get("/api/v1/integrations/google/callback", params={"state": state, "code": "valid-code"}).status_code == 400
    database.expire_all()
    assert module.credentials(database, "google")["refresh_token"] == "new-refresh"


def test_oauth_rejects_wrong_browser_and_expired_session(api, database):
    api.put("/api/v1/integrations/google", json={"config": {"client_id": "client-123"}})
    url = api.post("/api/v1/integrations/google/authorize", json={"services": ["gmail"]}).json()["url"]
    state = parse_qs(urlsplit(url).query)["state"][0]
    api.cookies.delete("pablo_oauth")
    assert api.get("/api/v1/integrations/google/callback", params={"state": state, "code": "code"}).status_code == 403
    url = api.post("/api/v1/integrations/google/authorize", json={"services": ["gmail"]}).json()["url"]
    state = parse_qs(urlsplit(url).query)["state"][0]
    session = database.get(Session, security.digest("test-session"))
    session.expires = 1
    database.commit()
    assert api.get("/api/v1/integrations/google/callback", params={"state": state, "code": "code"}).status_code == 403


def test_google_refresh_encrypts_rotated_token_and_requests_calendar(database, remote):
    google_credentials(database, expired=True)

    def handler(request):
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "rotated-access", "refresh_token": "rotated-refresh", "expires_in": 3600})
        assert request.headers["Authorization"] == "Bearer rotated-access"
        assert request.url.params["singleEvents"] == "true"
        return httpx.Response(200, json={"items": [{"id": "event-one", "summary": "Reunión"}], "nextPageToken": "next-page"})

    requests = remote(handler)
    result = module.google_calendar_list(database, {"limit": 5}, None)
    assert len(requests) == 2
    assert result["events"][0]["summary"] == "Reunión"
    assert result["next_page_token"] == "next-page"
    row = database.get(module.Integration, "google")
    assert "rotated-refresh" not in row.encrypted
    assert module.credentials(database, "google")["refresh_token"] == "rotated-refresh"


def test_google_rejects_ungranted_scopes_before_remote_call(database, remote):
    google_credentials(database, scopes=module.SCOPES["calendar"])
    requests = remote(lambda request: pytest.fail("No HTTP call allowed"))
    with pytest.raises(ValueError, match="permisos"):
        module.email_list(database, {}, None)
    assert requests == []


def test_calendar_create_validation_idempotency_and_no_invites(database, remote):
    google_credentials(database)
    requests = remote(lambda request: httpx.Response(200, json={"id": "created-event", "summary": "Entrega", "htmlLink": "https://calendar.google.com/event"}))
    with pytest.raises(ValueError, match="ISO 8601"):
        module.google_calendar_create(database, {"title": "Entrega", "start": "2026-10-01T09:00:00", "end": "2026-10-01T10:00:00"}, None)
    assert requests == []
    result = module.google_calendar_create(database, {"title": "Entrega", "start": "2026-10-01T09:00:00+02:00", "end": "2026-10-01T10:00:00+02:00", "_idempotency_key": "run:1"}, None)
    assert result["verified"]
    body = json.loads(requests[0].content)
    assert body["id"] == module.hashlib.sha256(b"run:1").hexdigest()
    assert requests[0].url.params["sendUpdates"] == "none"
    assert "attendees" not in body


def test_gmail_mime_send_and_header_injection(database, remote):
    google_credentials(database)
    requests = remote(lambda request: httpx.Response(200, json={"id": "gmail-id", "threadId": "thread-id"}))
    with pytest.raises(ValueError):
        module.email_send(database, {"to": "one@example.com\r\nBcc: secret@example.com", "subject": "hola", "body": "body"}, None)
    assert requests == []
    result = module.email_send(database, {"to": "Pablo <pablo@example.com>", "subject": "Entrega mañana", "body": "Texto con ñ y tildes."}, None)
    assert result["sent"]
    raw = base64.urlsafe_b64decode(json.loads(requests[0].content)["raw"])
    message = BytesParser(policy=policy.default).parsebytes(raw)
    assert message["Subject"] == "Entrega mañana"
    assert "Texto con ñ" in message.get_content()


def test_gmail_reads_nested_plain_text_without_attachments(database, remote):
    google_credentials(database)
    encoded = base64.urlsafe_b64encode("Hola desde el correo".encode()).decode().rstrip("=")
    remote(lambda request: httpx.Response(200, json={"id": "message", "payload": {"headers": [{"name": "Subject", "value": "Asunto"}, {"name": "Received", "value": "private metadata"}], "parts": [{"mimeType": "multipart/alternative", "parts": [{"mimeType": "text/plain", "body": {"data": encoded}}]}]}}))
    result = module.email_read(database, {"id": "message"}, None)
    assert result["text"] == "Hola desde el correo"
    assert result["headers"] == {"subject": "Asunto"}
    assert result["attachments_loaded"] is False


def test_github_write_requires_token_and_preserves_content(database, remote):
    args = {"repository": "owner/repo", "branch": "work", "path": "src/file.py", "message": "Fix", "content": "  indented = True\n", "sha": "a" * 40}
    requests = remote(lambda request: httpx.Response(200, json={"content": {"path": "src/file.py", "sha": "b" * 40}, "commit": {"sha": "c" * 40}}))
    with pytest.raises(ValueError, match="token"):
        module.github_write(database, args, None)
    assert requests == []
    module._store(database, "github", {"token": "github-private"})
    result = module.github_write(database, args, None)
    body = json.loads(requests[0].content)
    assert base64.b64decode(body["content"]).decode() == args["content"]
    assert body["sha"] == "a" * 40
    assert result["verified"]
    assert requests[0].headers["Authorization"] == "Bearer github-private"


def test_github_path_rejects_traversal_and_url_injection(database, remote):
    remote(lambda request: pytest.fail("No HTTP call allowed"))
    for path in ("../secret", "/root/token", "src/../secret", "src\\secret"):
        with pytest.raises(ValueError):
            module.github_read(database, {"repository": "owner/repo", "path": path}, None)
    with pytest.raises(ValueError):
        module.github_tree(database, {"repository": "owner/repo?url=https://evil"}, None)


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fd00::1", "0.0.0.0"])
def test_webhook_rejects_private_networks(monkeypatch, address):
    monkeypatch.setattr(module.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", (address, 443))])
    with pytest.raises(ValueError, match="HTTPS pública"):
        module._webhook_target("https://webhook.example/production")


def test_webhook_rejects_credentials_redirects_and_pins_dns(database, remote, monkeypatch):
    for url in ("http://webhook.example/production", "https://user:pass@webhook.example/a", "https://webhook.example:8443/a", "https://webhook.example/a#b"):
        with pytest.raises(ValueError):
            module._webhook_target(url)
    monkeypatch.setattr(module.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))])
    module._store(database, "n8n", {"webhook_url": "https://webhook.example/production", "token": "hook-token"})
    requests = remote(lambda request: httpx.Response(302, headers={"Location": "http://127.0.0.1/private"}))
    with pytest.raises(ValueError, match="HTTP 302"):
        module.n8n_trigger(database, {"payload": {"title": "test"}}, None)
    assert len(requests) == 1
    assert requests[0].url.host == "93.184.216.34"
    assert requests[0].headers["Host"] == "webhook.example"
    assert requests[0].extensions["sni_hostname"] == "webhook.example"


def test_webhook_configuration_encrypts_secret_url(api, database, monkeypatch):
    monkeypatch.setattr(module.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))])
    secret_url = "https://webhook.example/webhook/private-secret?key=more-secrets"
    response = api.put("/api/v1/integrations/n8n", json={"config": {"webhook_url": secret_url}})
    assert response.status_code == 200
    database.expire_all()
    row = database.get(module.Integration, "n8n")
    assert "private-secret" not in json.dumps(row.config)
    assert "private-secret" not in row.encrypted
    assert "private-secret" not in json.dumps(module.integration_status(database))
    assert module.credentials(database, "n8n")["webhook_url"] == secret_url


def test_web_search_has_honest_fallback_and_brave_results(database, remote):
    def handler(request):
        if request.url.host == "es.wikipedia.org":
            return httpx.Response(200, json={"query": {"search": [{"title": "Algoritmo", "pageid": 123, "snippet": "Un <b>algoritmo</b>"}]}})
        return httpx.Response(200, json={"web": {"results": [{"title": "Doc", "url": "https://example.com", "description": "Descripción"}]}})
    requests = remote(handler)
    fallback = module.web_search(database, {"query": "algoritmos"}, None)
    assert "Wikipedia" in fallback["provider"]
    assert "Solo Wikipedia" in fallback["scope"]
    assert fallback["results"][0]["snippet"] == "Un algoritmo"
    module._store(database, "search", {"api_key": "brave-key"})
    result = module.web_search(database, {"query": "documentación", "limit": 3}, None)
    assert result["provider"] == "Brave Search"
    assert requests[-1].headers["X-Subscription-Token"] == "brave-key"


def test_web_search_uses_wikipedia_rest_when_legacy_endpoint_is_blocked(database, remote):
    def handler(request):
        if request.url.path == "/w/api.php":
            return httpx.Response(403, text="blocked")
        assert request.url.path == "/w/rest.php/v1/search/page"
        return httpx.Response(200, json={"pages": [{
            "title": "n8n", "key": "N8n", "excerpt": "Automatización de <span>flujos</span>",
        }]})

    requests = remote(handler)
    result = module.web_search(database, {"query": "n8n"}, None)
    assert len(requests) == 2
    assert result["results"] == [{
        "title": "n8n",
        "url": "https://es.wikipedia.org/wiki/N8n",
        "snippet": "Automatización de flujos",
    }]
    assert requests[-1].headers["Api-User-Agent"].startswith("PABLO-OS/")


def test_drive_exports_docs_and_escapes_search_query(database, remote):
    google_credentials(database)
    def handler(request):
        if request.url.path.endswith("/export"):
            return httpx.Response(200, text="Contenido del documento")
        if request.url.path.endswith("/files/doc"):
            return httpx.Response(200, json={"id": "doc", "name": "Documento", "mimeType": "application/vnd.google-apps.document"})
        return httpx.Response(200, json={"files": []})
    requests = remote(handler)
    assert module.drive_read(database, {"id": "doc"}, None)["text"] == "Contenido del documento"
    module.drive_list(database, {"query": "Pablo's"}, None)
    assert "Pablo\\'s" in requests[-1].url.params["q"]


def test_notion_create_chunks_text_and_returns_real_result(database, remote):
    module._store(database, "notion", {"token": "notion-key"})
    requests = remote(lambda request: httpx.Response(200, json={"id": "notion-page", "url": "https://notion.so/page"}))
    result = module.notion_create(database, {"parent_id": "a" * 32, "title": "Notas", "content": "n" * 5000}, None)
    assert result["verified"]
    body = json.loads(requests[0].content)
    assert len(body["children"]) == 3
    assert all(len(block["paragraph"]["rich_text"][0]["text"]["content"]) <= 1900 for block in body["children"])


def test_remote_errors_do_not_expose_credentials_or_response_body(database, remote):
    remote(lambda request: httpx.Response(401, json={"error": "SECRET-TOKEN secret-email@example.com"}))
    with pytest.raises(ValueError) as exc:
        module.github_tree(database, {"repository": "owner/repo"}, None)
    assert "SECRET" not in str(exc.value)
    assert "HTTP 401" in str(exc.value)


def test_all_remote_writes_require_critical_approval():
    class Registry:
        def __init__(self):
            self.tools = {}
        def register(self, tool):
            self.tools[tool.id] = tool
    from dataclasses import make_dataclass
    tool = make_dataclass("Tool", ["id", "risk", "agent", "execute"])
    registry = Registry()
    module.register_integrations(registry, tool)
    for name in ("email.send", "google_calendar.create", "github.branch", "github.write", "n8n.trigger", "notion.create"):
        assert registry.tools[name].risk == "CRITICAL"
    assert registry.tools["daily.summary"].risk == "SAFE"
    assert len(registry.tools) == 18


@pytest.mark.parametrize("code,expected", [("invalid_grant", "Autorizar en Google"), ("invalid_client", "ID y el secreto"), ("unauthorized_client", "ID y el secreto"), ("unknown", "HTTP 400")])
def test_google_refresh_errors_are_actionable_and_private(database, remote, code, expected):
    google_credentials(database, expired=True)
    calls = remote(lambda request: httpx.Response(400, json={"error": code, "error_description": "private-token-and-email"}))
    with pytest.raises(ValueError, match=expected) as error:
        module.google_calendar_list(database, {}, None)
    assert "private-token-and-email" not in str(error.value)
    assert len(calls) == 1  # Never retry the failed refresh or send the calendar request.
    assert calls[0].url.host == "oauth2.googleapis.com"


@pytest.mark.parametrize("body", [b"not json", b"[]", b"x" * 9000])
def test_google_refresh_unexpected_error_body_is_safe(remote, body):
    remote(lambda request: httpx.Response(400, content=body))
    with pytest.raises(ValueError, match="HTTP 400"):
        module._request("POST", "https://oauth2.googleapis.com/token", data={})
