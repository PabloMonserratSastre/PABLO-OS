"""Authenticated connectors. Remote writes are registered as CRITICAL, never API shortcuts.

Credentials are encrypted independently of the database/export. HTTP failures deliberately
omit remote response bodies and URLs, which may contain personal data or credentials.
"""

import base64
import ctypes
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import socket
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import getaddresses
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import JSON, Integer, String, Text, delete
from sqlalchemy.orm import Mapped, mapped_column

from .db import DB, Base, Session, audit, now
from .security import digest, require_user


class Integration(Base):
    __tablename__ = "integrations"
    id: Mapped[str] = mapped_column(String(30), primary_key=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    encrypted: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[str] = mapped_column(String(40), default=now)


class OAuthState(Base):
    __tablename__ = "oauth_states"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    encrypted: Mapped[str] = mapped_column(Text)
    expires: Mapped[int] = mapped_column(Integer)
    session_id: Mapped[str] = mapped_column(String(64))


PROVIDERS = {
    "google": ({"client_id", "redirect_uri"}, {"client_secret"}),
    "github": (set(), {"token"}),
    "n8n": ({"webhook_url"}, {"token"}),
    "notion": (set(), {"token"}),
    "search": (set(), {"api_key"}),
}
ENV = {
    "google": {"client_id": "GOOGLE_CLIENT_ID", "client_secret": "GOOGLE_CLIENT_SECRET"},
    "github": {"token": "GITHUB_TOKEN"},
    "n8n": {"webhook_url": "N8N_WEBHOOK_URL", "token": "N8N_WEBHOOK_TOKEN"},
    "notion": {"token": "NOTION_TOKEN"},
    "search": {"api_key": "BRAVE_SEARCH_API_KEY"},
}
SCOPES = {
    "calendar": ["https://www.googleapis.com/auth/calendar.events"],
    "gmail": ["https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.send"],
    "drive": ["https://www.googleapis.com/auth/drive.readonly"],
}


def _windows_protect(value: bytes, decrypt=False) -> bytes:
    """Use the Windows user's DPAPI vault to protect the local Fernet master key."""
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(value)
    source = Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.windll.crypt32
    if decrypt:
        success = crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
    else:
        success = crypt.CryptProtectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
    if not success:
        raise ValueError("No se pudo acceder al almacén seguro de Windows.")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        ctypes.windll.kernel32.LocalFree(target.data)


def _cipher() -> Fernet:
    supplied = os.getenv("PABLO_SECRET_KEY")
    if supplied:
        try:
            return Fernet(supplied.encode())
        except ValueError:
            raise ValueError("PABLO_SECRET_KEY debe contener una clave Fernet válida.") from None
    path = Path(os.getenv("PABLO_SECRET_KEY_FILE", ".pablo-secrets.key")).resolve()
    if not path.exists():
        key = Fernet.generate_key()
        stored = b"DPAPI:" + _windows_protect(key) if os.name == "nt" else key
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "wb") as stream:
                stream.write(stored)
    try:
        value = path.read_bytes()
        if value.startswith(b"DPAPI:"):
            if os.name != "nt":
                raise ValueError("La clave pertenece a Windows. Reconecta tus integraciones en este equipo.")
            value = _windows_protect(value[6:], decrypt=True)
        return Fernet(value)
    except OSError:
        raise ValueError("No se puede leer la clave de integraciones. Revisa PABLO_SECRET_KEY_FILE.") from None


def seal(value: dict) -> str:
    return _cipher().encrypt(json.dumps(value, ensure_ascii=False).encode()).decode()


def unseal(value: str) -> dict:
    if not value:
        return {}
    try:
        return json.loads(_cipher().decrypt(value.encode()))
    except (InvalidToken, json.JSONDecodeError):
        raise ValueError("No se pueden descifrar las credenciales. Restaura la clave o reconecta la integración.") from None


def credentials(db, provider: str) -> dict:
    row = db.get(Integration, provider)
    if row and row.config.get("disabled"):
        return {}
    values = {k: os.getenv(v, "") for k, v in ENV.get(provider, {}).items()}
    if row:
        values.update(row.config)
        values.update(unseal(row.encrypted))
    return values


def approval_context(db, tool):
    provider = {"email.send": "google", "google_calendar.create": "google", "github.branch": "github", "github.write": "github", "n8n.trigger": "n8n", "notion.create": "notion"}.get(tool)
    if not provider:
        return None
    row = db.get(Integration, provider)
    values = credentials(db, provider)
    fingerprint = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
    # Hostname is reviewable; webhook path and token remain private.
    destination = urlsplit(values.get("webhook_url", "")).hostname if provider == "n8n" else provider
    return {"provider": provider, "destination": destination, "configuration": fingerprint,
            "updated_at": row.updated_at if row else "environment"}


def _store(db, provider, values, config=None):
    row = db.get(Integration, provider)
    if not row:
        row = Integration(id=provider, config={})
        db.add(row)
    if config is not None:
        row.config = config
    row.encrypted, row.updated_at = seal(values), now()
    db.flush()
    return row


def _text(args, key, limit=1000, required=True, strip=True):
    value = args.get(key, "")
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError(f"El campo {key} requiere texto de hasta {limit} caracteres.")
    return value.strip() if strip else value


def _limit(args, default=20, maximum=100):
    value = args.get("limit", default)
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= maximum:
        raise ValueError(f"limit debe ser un entero entre 1 y {maximum}.")
    return value


def _request(method, url, *, headers=None, params=None, json_body=None, data=None, extensions=None, raw=False):
    """Bounded, redirect-free HTTP; no automatic replay of remote mutations."""
    try:
        with httpx.Client(timeout=25, follow_redirects=False, trust_env=False) as client:
            with client.stream(method, url, headers=headers, params=params, json=json_body,
                               data=data, extensions=extensions) as response:
                if not response.is_success:
                    if url == "https://oauth2.googleapis.com/token" and response.status_code in {400, 401}:
                        # Read only a bounded error code; never expose Google's body or secrets.
                        error_body = bytearray()
                        for chunk in response.iter_bytes(chunk_size=1024):
                            error_body.extend(chunk)
                            if len(error_body) > 8192:
                                break
                        try:
                            payload = json.loads(error_body) if len(error_body) <= 8192 else {}
                            code = payload.get("error") if isinstance(payload, dict) else None
                        except (ValueError, UnicodeDecodeError):
                            code = None
                        if code == "invalid_grant":
                            raise ValueError("La autorización de Google ha caducado o se ha revocado. Ve a Integraciones, abre Google y pulsa Autorizar en Google para volver a conectar tu cuenta.")
                        if code in {"invalid_client", "unauthorized_client"}:
                            raise ValueError("Google no acepta las credenciales de la aplicación. Revisa el ID y el secreto del cliente en Integraciones > Google y vuelve a autorizar.")
                    raise ValueError(f"El servicio devolvió HTTP {response.status_code}. Revisa conexión y permisos.")
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > 3_000_000:
                        raise ValueError("La respuesta supera el límite de 3 MB. Acota la consulta.")
        if raw:
            return bytes(content).decode("utf-8", errors="replace")
        return json.loads(content) if content else {}
    except (httpx.HTTPError, OSError):
        if method.upper() in {"GET", "HEAD"}:
            raise ValueError("No se pudo conectar con el servicio para consultar los datos. Comprueba Internet y que PABLO OS tenga acceso a la red; si se inició desde Codex, ciérralo y ábrelo desde el acceso directo del escritorio. No se han realizado cambios.") from None
        raise ValueError("No se pudo confirmar la respuesta del servicio. Comprueba su estado antes de repetir cambios.") from None
    except json.JSONDecodeError:
        raise ValueError("El servicio devolvió una respuesta JSON no válida.") from None


def _google(db, service, method, path, **kwargs):
    values = credentials(db, "google")
    if not values.get("access_token"):
        raise ValueError("Conecta Google desde Integraciones y autoriza este servicio.")
    granted = set(values.get("scopes", []))
    required = SCOPES[service][1] if service == "gmail" and method == "POST" else SCOPES[service][0]
    if required not in granted:
        raise ValueError(f"Reconecta Google y concede permisos para {service}.")
    if float(values.get("expires_at", 0)) <= time.time() + 60:
        if not values.get("refresh_token"):
            raise ValueError("La autorización de Google caducó. Vuelve a conectar tu cuenta.")
        token = _request("POST", "https://oauth2.googleapis.com/token", data={
            "client_id": values.get("client_id", ""), "client_secret": values.get("client_secret", ""),
            "refresh_token": values["refresh_token"], "grant_type": "refresh_token",
        })
        if not token.get("access_token"):
            raise ValueError("Google no devolvió una autorización válida.")
        row = db.get(Integration, "google")
        stored = unseal(row.encrypted)
        stored.update({"access_token": token["access_token"], "expires_at": time.time() + int(token.get("expires_in", 3600))})
        if token.get("refresh_token"):
            stored["refresh_token"] = token["refresh_token"]
        _store(db, "google", stored)
        values.update(stored)
    bases = {"calendar": "https://www.googleapis.com/calendar/v3/", "gmail": "https://gmail.googleapis.com/gmail/v1/users/me/", "drive": "https://www.googleapis.com/drive/v3/"}
    return _request(method, bases[service] + path, headers={"Authorization": "Bearer " + values["access_token"]}, **kwargs)


def google_calendar_list(db, args, project_id):
    calendar = quote(_text(args, "calendar_id", required=False) or "primary", safe="")
    params = {"maxResults": _limit(args), "singleEvents": "true", "orderBy": "startTime",
              "timeMin": _text(args, "start", 100, False) or datetime.now(timezone.utc).isoformat()}
    if args.get("end"):
        params["timeMax"] = _text(args, "end", 100)
    if args.get("page_token"):
        params["pageToken"] = _text(args, "page_token", 2000)
    if args.get("query"):
        params["q"] = _text(args, "query", 500)
    data = _google(db, "calendar", "GET", f"calendars/{calendar}/events", params=params)
    from .db import Owner
    owner = db.get(Owner, 1)
    return {"timezone": (owner.settings or {}).get("timezone", "Europe/Madrid") if owner else "Europe/Madrid", "events": [{k: e.get(k) for k in ("id", "summary", "description", "start", "end", "htmlLink", "location")} for e in data.get("items", [])], "next_page_token": data.get("nextPageToken")}


def google_calendar_create(db, args, project_id):
    start, end = _text(args, "start", 100), _text(args, "end", 100)
    try:
        begin, finish = datetime.fromisoformat(start.replace("Z", "+00:00")), datetime.fromisoformat(end.replace("Z", "+00:00"))
        if not begin.tzinfo or not finish.tzinfo or finish <= begin:
            raise ValueError()
    except ValueError:
        raise ValueError("Usa start y end ISO 8601 con zona horaria y final posterior al inicio.") from None
    body = {"summary": _text(args, "title", 300), "start": {"dateTime": start}, "end": {"dateTime": end},
            "description": _text(args, "description", 20000, False), "location": _text(args, "location", 1000, False)}
    if args.get("_idempotency_key"):
        body["id"] = hashlib.sha256(str(args["_idempotency_key"]).encode()).hexdigest()
    calendar = quote(_text(args, "calendar_id", required=False) or "primary", safe="")
    data = _google(db, "calendar", "POST", f"calendars/{calendar}/events", json_body=body, params={"sendUpdates": "none"})
    return {"id": data.get("id"), "title": data.get("summary"), "url": data.get("htmlLink"), "verified": bool(data.get("id"))}


def email_list(db, args, project_id):
    params = {"maxResults": _limit(args, 10, 20), "q": _text(args, "query", 1000, False) or "in:inbox"}
    if args.get("page_token"):
        params["pageToken"] = _text(args, "page_token", 2000)
    data = _google(db, "gmail", "GET", "messages", params=params)
    messages = []
    for entry in data.get("messages", []):
        message = _google(db, "gmail", "GET", "messages/" + quote(entry["id"], safe=""), params={"format": "metadata", "metadataHeaders": ["Subject", "From", "Date"]})
        headers = {h["name"].lower(): h["value"] for h in message.get("payload", {}).get("headers", [])}
        messages.append({"id": message["id"], "thread_id": message.get("threadId"), "subject": headers.get("subject", ""), "from": headers.get("from", ""), "date": headers.get("date", ""), "snippet": message.get("snippet", "")})
    return {"messages": messages, "next_page_token": data.get("nextPageToken")}


def email_read(db, args, project_id):
    data = _google(db, "gmail", "GET", "messages/" + quote(_text(args, "id", 200), safe=""), params={"format": "full"})
    texts = []
    def visit(part, depth=0):
        if depth > 10:
            return
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            encoded = part["body"]["data"]
            texts.append(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8", errors="replace"))
        for child in part.get("parts", []):
            visit(child, depth + 1)
    visit(data.get("payload", {}))
    allowed = {"subject", "from", "to", "date"}
    headers = {h["name"].lower(): h["value"] for h in data.get("payload", {}).get("headers", []) if h["name"].lower() in allowed}
    return {"id": data["id"], "headers": headers, "text": "\n".join(texts)[:50000] or data.get("snippet", ""), "source": "Gmail", "attachments_loaded": False}


def email_send(db, args, project_id):
    recipients = _text(args, "to", 2000)
    addresses = getaddresses([recipients])
    if "\r" in recipients or "\n" in recipients or not addresses or len(addresses) > 20 or any(not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", email) for _, email in addresses):
        raise ValueError("Introduce entre 1 y 20 destinatarios válidos, separados por coma.")
    subject = _text(args, "subject", 300)
    if "\r" in subject or "\n" in subject:
        raise ValueError("El asunto debe ocupar una sola línea.")
    message = EmailMessage()
    message["To"], message["Subject"] = recipients, subject
    message.set_content(_text(args, "body", 100000, strip=False))
    encoded = base64.urlsafe_b64encode(message.as_bytes()).decode()
    data = _google(db, "gmail", "POST", "messages/send", json_body={"raw": encoded})
    return {"id": data.get("id"), "thread_id": data.get("threadId"), "sent": bool(data.get("id")), "to": recipients, "subject": subject}


def _github(db, method, path, **kwargs):
    token = credentials(db, "github").get("token")
    if method != "GET" and not token:
        raise ValueError("Conecta GitHub con un token que tenga permiso de escritura en el repositorio.")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "PabloOS", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = "Bearer " + token
    return _request(method, "https://api.github.com/" + path, headers=headers, **kwargs)


def _repo(args):
    repo = _text(args, "repository", 300)
    if not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*/[A-Za-z0-9_.-]+", repo):
        raise ValueError("Escribe repository como propietario/nombre.")
    return "repos/" + repo


def _ref(args, key="ref", default="HEAD"):
    value = _text(args, key, 250, False) or default
    if any(x in value for x in ("..", "@{", "\\")) or any(c in value for c in " ~^:?*[\r\n") or value.startswith("/") or value.endswith("/"):
        raise ValueError("Referencia de Git no válida.")
    return quote(value, safe="")


def github_tree(db, args, project_id):
    data = _github(db, "GET", _repo(args) + "/git/trees/" + _ref(args), params={"recursive": "1"})
    entries = data.get("tree", [])
    return {"sha": data.get("sha"), "files": [{k: f.get(k) for k in ("path", "type", "size", "sha")} for f in entries[:2000]], "truncated": data.get("truncated", False) or len(entries) > 2000}


def _file_path(args):
    value = _text(args, "path", 1000)
    if value.startswith("/") or "\\" in value or any(p in {"", ".", ".."} for p in value.split("/")):
        raise ValueError("La ruta debe ser relativa al repositorio y no contener '..'.")
    return quote(value, safe="/")


def github_read(db, args, project_id):
    data = _github(db, "GET", _repo(args) + "/contents/" + _file_path(args), params={"ref": _text(args, "ref", 250, False) or "HEAD"})
    if not isinstance(data, dict) or data.get("type") != "file" or data.get("encoding") != "base64":
        raise ValueError("Elige un archivo de texto de hasta 1 MB del repositorio.")
    raw = base64.b64decode(data.get("content", ""))
    return {"path": data.get("path"), "sha": data.get("sha"), "content": raw.decode("utf-8", errors="replace")[:100000], "truncated": len(raw) > 100000, "url": data.get("html_url")}


def github_diff(db, args, project_id):
    data = _github(db, "GET", _repo(args) + "/compare/" + _ref(args, "base") + "..." + _ref(args, "head"))
    files = data.get("files", [])
    return {"status": data.get("status"), "ahead_by": data.get("ahead_by"), "behind_by": data.get("behind_by"), "files": [{"path": f["filename"], "status": f["status"], "additions": f["additions"], "deletions": f["deletions"], "patch": f.get("patch", "")[:20000]} for f in files[:100]], "truncated": len(files) >= 100, "url": data.get("html_url")}


def github_branch(db, args, project_id):
    branch = _text(args, "branch", 200)
    _ref(args, "branch")
    if branch in {"main", "master", "HEAD"} or branch.endswith(".lock") or "//" in branch:
        raise ValueError("Elige un nombre válido para una rama nueva.")
    source = _github(db, "GET", _repo(args) + "/commits/" + _ref(args, "from_ref"))
    result = _github(db, "POST", _repo(args) + "/git/refs", json_body={"ref": "refs/heads/" + branch, "sha": source["sha"]})
    return {"ref": result.get("ref"), "sha": result.get("object", {}).get("sha"), "verified": bool(result.get("ref"))}


def github_write(db, args, project_id):
    branch = _text(args, "branch", 200)
    _ref(args, "branch")
    path = _file_path(args)
    # The caller must provide the reviewed SHA for edits; missing SHA only creates a new file.
    body = {"message": _text(args, "message", 300), "branch": branch,
            "content": base64.b64encode(_text(args, "content", 500000, False, strip=False).encode()).decode()}
    if args.get("sha"):
        sha = _text(args, "sha", 64)
        if not re.fullmatch(r"[a-f0-9]{40,64}", sha):
            raise ValueError("sha debe ser el identificador del archivo revisado.")
        body["sha"] = sha
    data = _github(db, "PUT", _repo(args) + "/contents/" + path, json_body=body)
    return {"path": data.get("content", {}).get("path"), "sha": data.get("content", {}).get("sha"), "commit": data.get("commit", {}).get("sha"), "url": data.get("content", {}).get("html_url"), "verified": bool(data.get("commit", {}).get("sha"))}


def _webhook_target(value):
    try:
        url = urlsplit(value)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.fragment or url.port not in {None, 443}:
            raise ValueError()
        host = url.hostname.encode("idna").decode("ascii")
        addresses = sorted({entry[4][0] for entry in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
        if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise ValueError()
    except (ValueError, UnicodeError, OSError):
        raise ValueError("n8n requiere una URL HTTPS pública en puerto 443, sin credenciales ni redes privadas.") from None
    # Pin DNS result and preserve TLS certificate verification for the original hostname.
    target = str(httpx.URL(value).copy_with(host=addresses[0]))
    return target, {"Host": host}, {"sni_hostname": host}


def n8n_trigger(db, args, project_id):
    values = credentials(db, "n8n")
    if not values.get("webhook_url"):
        raise ValueError("Configura un webhook de producción de n8n en Integraciones.")
    payload = args.get("payload", {})
    if not isinstance(payload, dict) or len(json.dumps(payload)) > 100000:
        raise ValueError("payload debe ser un objeto JSON de hasta 100 KB.")
    target, headers, extensions = _webhook_target(values["webhook_url"])
    if values.get("token"):
        headers["Authorization"] = "Bearer " + values["token"]
    if args.get("_idempotency_key"):
        headers["Idempotency-Key"] = str(args["_idempotency_key"])
    result = _request("POST", target, headers=headers, extensions=extensions, json_body=payload, raw=True)
    return {"accepted": True, "response": result[:10000], "detail": "Webhook entregado; la finalización del flujo depende de n8n."}


def web_search(db, args, project_id):
    query, count = _text(args, "query", 500), _limit(args, 5, 20)
    key = credentials(db, "search").get("api_key")
    if key:
        data = _request("GET", "https://api.search.brave.com/res/v1/web/search", headers={"X-Subscription-Token": key, "Accept": "application/json"}, params={"q": query, "count": count})
        results = [{"title": r.get("title"), "url": r.get("url"), "snippet": r.get("description", "")} for r in data.get("web", {}).get("results", [])]
        return {"provider": "Brave Search", "query": query, "results": results}
    data = _request("GET", "https://es.wikipedia.org/w/api.php", headers={"User-Agent": "PabloOS/1.0 (local knowledge search)"}, params={"action": "query", "list": "search", "srsearch": query, "srlimit": count, "format": "json"})
    return {"provider": "Wikipedia (búsqueda enciclopédica)", "query": query, "scope": "Solo Wikipedia; configura Brave Search para buscar en toda la web.", "results": [{"title": r["title"], "url": "https://es.wikipedia.org/?curid=" + str(r["pageid"]), "snippet": re.sub(r"<[^>]+>", "", r.get("snippet", ""))} for r in data.get("query", {}).get("search", [])]}


def drive_list(db, args, project_id):
    params = {"pageSize": _limit(args), "fields": "nextPageToken,files(id,name,mimeType,modifiedTime,webViewLink)", "q": "trashed = false"}
    query = _text(args, "query", 500, False)
    if query:
        params["q"] += " and fullText contains '" + query.replace("\\", "\\\\").replace("'", "\\'") + "'"
    if args.get("page_token"):
        params["pageToken"] = _text(args, "page_token", 2000)
    data = _google(db, "drive", "GET", "files", params=params)
    return {"files": data.get("files", []), "next_page_token": data.get("nextPageToken")}


def drive_read(db, args, project_id):
    file_id = quote(_text(args, "id", 200), safe="")
    metadata = _google(db, "drive", "GET", "files/" + file_id, params={"fields": "id,name,mimeType,size,webViewLink"})
    mime = metadata["mimeType"]
    if mime == "application/vnd.google-apps.document":
        text = _google(db, "drive", "GET", "files/" + file_id + "/export", params={"mimeType": "text/plain"}, raw=True)
    elif mime.startswith("text/") or mime in {"application/json", "application/xml"}:
        text = _google(db, "drive", "GET", "files/" + file_id, params={"alt": "media"}, raw=True)
    else:
        return {**metadata, "text": "", "detail": "Este lector admite Google Docs y archivos de texto. Descarga otros formatos desde Drive e impórtalos en Documentos."}
    return {**metadata, "text": text[:100000], "truncated": len(text) > 100000}


def _notion(db, method, path, **kwargs):
    token = credentials(db, "notion").get("token")
    if not token:
        raise ValueError("Conecta Notion y comparte las páginas con tu integración.")
    return _request(method, "https://api.notion.com/v1/" + path, headers={"Authorization": "Bearer " + token, "Notion-Version": "2022-06-28"}, **kwargs)


def notion_search(db, args, project_id):
    body = {"query": _text(args, "query", 500, False), "page_size": _limit(args), "filter": {"property": "object", "value": "page"}}
    if args.get("page_token"):
        body["start_cursor"] = _text(args, "page_token", 2000)
    data = _notion(db, "POST", "search", json_body=body)
    results = []
    for page in data.get("results", []):
        title = "".join(part.get("plain_text", "") for prop in page.get("properties", {}).values() if prop.get("type") == "title" for part in prop.get("title", []))
        results.append({"id": page["id"], "title": title, "url": page.get("url"), "last_edited_time": page.get("last_edited_time")})
    return {"pages": results, "next_page_token": data.get("next_cursor")}


def _notion_id(args, key="id"):
    value = _text(args, key, 36)
    if not re.fullmatch(r"[a-fA-F0-9-]{32,36}", value):
        raise ValueError("Introduce un identificador de página o bloque de Notion válido.")
    return value


def notion_read(db, args, project_id):
    params = {"page_size": _limit(args)}
    if args.get("page_token"):
        params["start_cursor"] = _text(args, "page_token", 2000)
    data = _notion(db, "GET", "blocks/" + _notion_id(args) + "/children", params=params)
    blocks = [{"id": block["id"], "type": block["type"], "has_children": block.get("has_children", False), "text": "".join(t.get("plain_text", "") for t in block.get(block["type"], {}).get("rich_text", []))} for block in data.get("results", [])]
    return {"blocks": blocks, "next_page_token": data.get("next_cursor"), "scope": "Bloques de primer nivel; lee los hijos por su identificador."}


def notion_create(db, args, project_id):
    title, content = _text(args, "title", 300), _text(args, "content", 100000, strip=False)
    children = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": content[i:i + 1900]}}]}} for i in range(0, len(content), 1900)]
    data = _notion(db, "POST", "pages", json_body={"parent": {"page_id": _notion_id(args, "parent_id")}, "properties": {"title": {"type": "title", "title": [{"type": "text", "text": {"content": title}}]}}, "children": children})
    return {"id": data.get("id"), "url": data.get("url"), "title": title, "verified": bool(data.get("id"))}


def register_integrations(registry, Tool):
    from .daily_digest import digest
    registry.register(Tool("daily.summary", "SAFE", "Productivity", digest))
    for name, risk, agent, execute in [
        ("google_calendar.list", "SAFE", "Calendar", google_calendar_list),
        ("google_calendar.create", "CRITICAL", "Calendar", google_calendar_create),
        ("email.list", "SAFE", "Email", email_list), ("email.read", "SAFE", "Email", email_read),
        ("email.send", "CRITICAL", "Email", email_send),
        ("github.tree", "SAFE", "GitHub", github_tree), ("github.read", "SAFE", "GitHub", github_read),
        ("github.diff", "SAFE", "GitHub", github_diff), ("github.branch", "CRITICAL", "GitHub", github_branch),
        ("github.write", "CRITICAL", "GitHub", github_write),
        ("n8n.trigger", "CRITICAL", "Automation", n8n_trigger), ("web.search", "SAFE", "Research", web_search),
        ("drive.list", "SAFE", "File", drive_list), ("drive.read", "SAFE", "File", drive_read),
        ("notion.search", "SAFE", "Research", notion_search), ("notion.read", "SAFE", "Research", notion_read),
        ("notion.create", "CRITICAL", "Productivity", notion_create),
    ]:
        registry.register(Tool(name, risk, agent, execute))


class ConnectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config: dict[str, str] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)


class GoogleAuthorize(BaseModel):
    model_config = ConfigDict(extra="forbid")
    services: list[str] = Field(default_factory=lambda: ["calendar", "gmail", "drive"], min_length=1, max_length=3)


router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])


@router.get("/google/calendar-events", dependencies=[Depends(require_user)])
def calendar_feed(start: datetime, end: datetime):
    if start.tzinfo is None or end.tzinfo is None or not 0 < (end - start).total_seconds() <= 62 * 86400:
        raise ValueError("Selecciona un intervalo de calendario de hasta 62 días con zona horaria.")
    with DB() as db:
        values = credentials(db, "google")
        if not values.get("access_token"):
            return {"events": [], "connected": False, "truncated": False}
        rows, page = [], None
        for _ in range(10):
            params = {"timeMin": start.isoformat(), "timeMax": end.isoformat(),
                      "singleEvents": "true", "orderBy": "startTime", "maxResults": 250}
            if page:
                params["pageToken"] = page
            data = _google(db, "calendar", "GET", "calendars/primary/events", params=params)
            for event in data.get("items", []):
                if event.get("status") == "cancelled":
                    continue
                begin, finish = event.get("start", {}), event.get("end", {})
                if not (begin.get("dateTime") or begin.get("date")) or not (finish.get("dateTime") or finish.get("date")):
                    continue
                rows.append({"id": "google:" + event["id"], "source": "google",
                             "title": event.get("summary") or "(Sin título)",
                             "start": begin.get("dateTime") or begin["date"] + "T00:00:00",
                             "end": finish.get("dateTime") or finish["date"] + "T00:00:00",
                             "all_day": bool(begin.get("date")),
                             "description": event.get("description", "")})
            page = data.get("nextPageToken")
            if not page:
                break
        db.commit()  # Persist a refreshed OAuth token when needed.
        return {"events": rows, "connected": True, "truncated": bool(page)}


@router.put("/{provider}", dependencies=[Depends(require_user)])
def configure(provider: str, body: ConnectionInput):
    if provider not in PROVIDERS:
        raise HTTPException(404, "Integración desconocida.")
    config_keys, secret_keys = PROVIDERS[provider]
    if set(body.config) - config_keys or set(body.secrets) - secret_keys or any(len(v) > 5000 for v in [*body.config.values(), *body.secrets.values()]):
        raise ValueError("Campos de conexión no válidos.")
    public = {k: v.strip() for k, v in body.config.items()}
    supplied = {k: v.strip() for k, v in body.secrets.items() if v.strip()}
    if provider == "n8n" and public.get("webhook_url"):
        _webhook_target(public["webhook_url"])
        # Webhook path/query frequently contain an access secret: encrypt the entire URL.
        supplied["webhook_url"] = public.pop("webhook_url")
    with DB() as db:
        row = db.get(Integration, provider)
        previous = unseal(row.encrypted) if row and row.encrypted else {}
        config = ((row.config if row else {}) | public) | {"disabled": False}
        if provider == "google" and row and (public.get("client_id", row.config.get("client_id")) != row.config.get("client_id") or "client_secret" in supplied):
            previous = {k: v for k, v in previous.items() if k == "client_secret"}
        _store(db, provider, previous | supplied, config)
        audit(db, "integration.configured", provider=provider)
        db.commit()
    return {"ok": True, "provider": provider}


@router.delete("/{provider}", dependencies=[Depends(require_user)])
def disconnect(provider: str):
    if provider not in PROVIDERS:
        raise HTTPException(404)
    with DB() as db:
        row = db.get(Integration, provider)
        if not row:
            row = Integration(id=provider)
            db.add(row)
        row.config, row.encrypted, row.updated_at = {"disabled": True}, "", now()
        if provider == "google":
            db.execute(delete(OAuthState))
        audit(db, "integration.disconnected", provider=provider)
        db.commit()
    return {"disconnected": True, "detail": "Credenciales locales eliminadas. Puedes revocar el acceso también en el proveedor."}


def _redirect_uri(values):
    origin = os.getenv("APP_ORIGIN", "http://localhost:8000").rstrip("/")
    expected = origin + "/api/v1/integrations/google/callback"
    configured = values.get("redirect_uri") or expected
    if configured != expected:
        raise ValueError("redirect_uri debe coincidir con APP_ORIGIN + /api/v1/integrations/google/callback.")
    return configured


@router.post("/google/authorize", dependencies=[Depends(require_user)])
def google_authorize(body: GoogleAuthorize, request: Request, response: Response):
    if any(s not in SCOPES for s in body.services):
        raise ValueError("Servicios Google válidos: calendar, gmail, drive.")
    with DB() as db:
        values = credentials(db, "google")
        if not values.get("client_id"):
            raise ValueError("Configura el ID de cliente OAuth de Google antes de conectar.")
        redirect_uri = _redirect_uri(values)
        state, verifier, browser = secrets.token_urlsafe(32), secrets.token_urlsafe(48), secrets.token_urlsafe(32)
        scopes = sorted({scope for service in body.services for scope in SCOPES[service]})
        pending = {"verifier": verifier, "browser": digest(browser), "scopes": scopes, "redirect_uri": redirect_uri, "client_id": values["client_id"]}
        db.execute(delete(OAuthState).where(OAuthState.expires < int(time.time())))
        db.add(OAuthState(id=digest(state), encrypted=seal(pending), session_id=digest(request.cookies.get("pablo_session", "")), expires=int(time.time()) + 600))
        db.commit()
    # Main session is SameSite=Strict; a separate nonce cookie accepts only this OAuth callback.
    response.set_cookie("pablo_oauth", browser, max_age=600, httponly=True, samesite="lax", secure=os.getenv("COOKIE_SECURE", "false") == "true", path="/api/v1/integrations/google/callback")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return {"url": "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({"client_id": values["client_id"], "redirect_uri": redirect_uri, "response_type": "code", "scope": " ".join(scopes), "state": state, "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true", "code_challenge": challenge, "code_challenge_method": "S256"})}


@router.get("/google/callback")
def google_callback(request: Request, state: str = "", code: str = "", error: str = ""):
    if not state or len(state) > 200 or len(code) > 5000:
        raise HTTPException(400, "Respuesta OAuth no válida.")
    with DB() as db:
        row = db.get(OAuthState, digest(state))
        if not row or row.expires < time.time():
            raise HTTPException(400, "La conexión caducó o ya se utilizó. Vuelve a conectar Google.")
        pending = unseal(row.encrypted)
        session = db.get(Session, row.session_id)
        if not session or session.expires < time.time() or not hmac.compare_digest(pending["browser"], digest(request.cookies.get("pablo_oauth", ""))):
            raise HTTPException(403, "La conexión debe completarse desde el navegador y la sesión que la iniciaron.")
        # Atomic one-time consumption before remote exchange also protects concurrent callbacks.
        claimed = db.execute(delete(OAuthState).where(OAuthState.id == row.id))
        db.commit()
        if not claimed.rowcount:
            raise HTTPException(400, "Esta conexión ya se utilizó.")
        if error or not code:
            raise HTTPException(400, "Google no autorizó la conexión. Puedes volver a intentarlo.")
        values = credentials(db, "google")
        if values.get("client_id") != pending["client_id"]:
            raise HTTPException(400, "La configuración cambió. Reinicia la conexión.")
        token = _request("POST", "https://oauth2.googleapis.com/token", data={"client_id": values["client_id"], "client_secret": values.get("client_secret", ""), "code": code, "code_verifier": pending["verifier"], "grant_type": "authorization_code", "redirect_uri": pending["redirect_uri"]})
        if not token.get("access_token"):
            raise ValueError("Google no devolvió una autorización válida.")
        current = db.get(Integration, "google")
        stored = unseal(current.encrypted) if current else {}
        stored.update({"access_token": token["access_token"], "expires_at": time.time() + int(token.get("expires_in", 3600)), "scopes": token.get("scope", " ".join(pending["scopes"])).split()})
        if token.get("refresh_token"):
            stored["refresh_token"] = token["refresh_token"]
        _store(db, "google", stored)
        audit(db, "integration.connected", provider="google")
        db.commit()
    response = RedirectResponse("/?integration=google&connected=1", status_code=303)
    response.delete_cookie("pablo_oauth", path="/api/v1/integrations/google/callback")
    return response


def integration_status(db):
    result = []
    for provider, name in [("google", "Google Calendar, Gmail y Drive"), ("github", "GitHub"), ("n8n", "n8n"), ("notion", "Notion"), ("search", "Búsqueda web")]:
        row = db.get(Integration, provider)
        try:
            values = credentials(db, provider)
            fault = False
        except ValueError:
            values, fault = {}, True
        if fault:
            status, detail = "ERROR", "No se pudieron descifrar las credenciales. Restaura la clave o reconecta."
        elif provider == "google":
            status = "CONNECTED" if values.get("access_token") and (values.get("refresh_token") or values.get("expires_at", 0) > time.time()) else "NEEDS_AUTH"
            detail = "Agenda, lectura/envío de correo y documentos, según los permisos concedidos."
        elif provider == "github":
            status = "CONFIGURED" if values.get("token") else "PUBLIC_READ"
            detail = "Árbol, archivos y comparaciones. Crear ramas y commits requiere token y aprobación."
        elif provider == "search":
            status = "CONFIGURED" if values.get("api_key") else "PUBLIC_READ"
            detail = "Brave Search configurado." if values.get("api_key") else "Búsqueda enciclopédica en Wikipedia. Añade una clave Brave para buscar en toda la web."
        else:
            status = "CONFIGURED" if values.get("webhook_url" if provider == "n8n" else "token") else "DISCONNECTED"
            detail = "Webhook HTTPS de producción con aprobación por ejecución." if provider == "n8n" else "Busca y lee páginas compartidas; crea páginas con aprobación."
        config = {k: v for k, v in (row.config if row else {}).items() if k in PROVIDERS[provider][0]}
        if provider == "google" and values.get("client_id"):
            config["client_id"] = values["client_id"]
            config["redirect_uri"] = values.get("redirect_uri") or os.getenv("APP_ORIGIN", "http://localhost:8000").rstrip("/") + "/api/v1/integrations/google/callback"
        result.append({"id": provider, "name": name, "status": status, "detail": detail, "configured": bool(values.get("client_id" if provider == "google" else "webhook_url" if provider == "n8n" else "api_key" if provider == "search" else "token")), "config": config, "scopes": values.get("scopes", []) if provider == "google" else [], "verified": provider == "google" and status == "CONNECTED"})
    return result
