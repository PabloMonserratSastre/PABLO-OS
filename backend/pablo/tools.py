import base64
import os
import re
from collections.abc import Callable
from dataclasses import dataclass

import httpx
from sqlalchemy import select

from .db import Item, Owner
from .integrations import register_integrations
from .item_tools import register as register_item_tools
from .knowledge import search, tokens
from .schedule_tools import register as register_schedule_tools
from .schemas import Record
from .workspace_tools import register_workspace_tools


@dataclass(frozen=True)
class Tool:
    id: str
    risk: str
    agent: str
    execute: Callable


class ToolRegistry:
    def __init__(self):
        self.tools: dict[str, Tool] = {}

    def register(self, tool: Tool):
        if tool.id in self.tools:
            raise ValueError("Herramienta ya registrada")
        self.tools[tool.id] = tool

    def get(self, name: str) -> Tool:
        if name not in self.tools:
            raise ValueError("Herramienta no disponible")
        return self.tools[name]

    def list(self):
        from .tool_contracts import ARGUMENTS

        return [{"id": t.id, "risk": t.risk, "agent": t.agent, "arguments": ARGUMENTS.get(t.id, {})} for t in self.tools.values()]


def create_record(db, args, kind, project_id):
    from .main import validate_record

    record = Record.model_validate(args)
    record = record.model_copy(update={"status": "TODO" if kind == "tasks" else "PLANNING",
                                      "project_id": record.project_id or project_id if kind == "tasks" else record.project_id})
    validate_record(db, record, kind)
    if record.project_id:
        project = db.get(Item, record.project_id)
        if not project or project.kind != "projects":
            raise ValueError("Proyecto no encontrado")
    data = record.model_dump(exclude={"title", "version"})
    if kind == "tasks":
        data["status"] = "TODO"
        data["project_id"] = record.project_id or project_id
    else:
        data["status"] = "PLANNING"
    item = Item(kind=kind, title=record.title, data=data)
    db.add(item)
    db.flush()
    return {"id": item.id, "title": item.title, "due": data.get("due", ""), "project_id": data.get("project_id"), "verified": db.get(Item, item.id) is not None}


def task_list(db, args, project_id):
    rows = db.scalars(select(Item).where(Item.kind == "tasks")).all()
    rows = [
        r
        for r in rows
        if r.data.get("status") not in {"DONE", "CANCELLED"}
        and (not project_id or r.data.get("project_id") == project_id)
        and (not args.get("due") or r.data.get("due") == args["due"])
        and (not args.get("query") or str(args["query"]).casefold() in r.title.casefold())
    ]
    rows.sort(
        key=lambda r: (
            {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(r.data.get("priority"), 1),
            r.data.get("due") or "9999",
        )
    )
    return [{"id": r.id, "title": r.title, **r.data} for r in rows[:50]]


def memory_search(db, args, project_id):
    owner = db.get(Owner, 1)
    if not owner.settings.get("memory_enabled", True):
        return []
    query = tokens(str(args.get("query", "")))
    allowed = owner.settings.get("memory_categories", ["user", "project", "knowledge"])
    rows = db.scalars(select(Item).where(Item.kind == "memory")).all()
    return [
        {"id": r.id, "title": r.title, **r.data}
        for r in rows
        if r.data.get("category") in allowed
        and (not r.data.get("project_id") or r.data.get("project_id") == project_id)
        and (r.data.get("pinned") or set(query) & set(tokens(r.title + " " + r.data.get("description", ""))))
    ][:10]


def github_inspect(db, args, project_id):
    repo = str(args.get("repository", "")).strip()
    repo = re.sub(r"^https?://github\.com/", "", repo, flags=re.I).removesuffix(".git").strip("/")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("Escribe el repositorio como propietario/nombre.")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "PABLO-OS/0.4"}
    from .integrations import credentials
    token = credentials(db, "github").get("token") or os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
        response = client.get("https://api.github.com/repos/" + repo, headers=headers)
        if not response.is_success:
            raise ValueError(
                f"GitHub devolvió HTTP {response.status_code}. Revisa el repositorio y sus permisos."
            )
        data = response.json()
        readme = client.get("https://api.github.com/repos/" + repo + "/readme", headers=headers)
        content = ""
        if readme.is_success:
            content = base64.b64decode(readme.json().get("content", "")).decode("utf-8", errors="replace")[
                :10000
            ]
    return {
        "repository": data["full_name"],
        "url": data["html_url"],
        "language": data.get("language"),
        "description": data.get("description"),
        "default_branch": data["default_branch"],
        "open_issues": data["open_issues_count"],
        "readme": content,
        "scope": "Metadatos y README; no se han ejecutado tests ni analizado todos los archivos.",
    }


def report_create(db, args, project_id):
    title, content = str(args.get("title", "")).strip(), str(args.get("content", ""))
    if not title or len(title) > 300 or not content or len(content) > 30000:
        raise ValueError("El informe requiere título y contenido (máximo 30.000 caracteres).")
    item = Item(kind="artifacts", title=title, data={"description": content, "project_id": project_id})
    db.add(item)
    db.flush()
    return {"id": item.id, "title": title, "verified": True}


registry = ToolRegistry()
for tool in [
    Tool("tasks.list", "SAFE", "Productivity", task_list),
    Tool(
        "projects.create",
        "MODERATE",
        "Software Engineer",
        lambda db, a, p: create_record(db, a, "projects", p),
    ),
    Tool("tasks.create", "MODERATE", "Productivity", lambda db, a, p: create_record(db, a, "tasks", p)),
    Tool("memory.search", "SAFE", "Productivity", memory_search),
    Tool("documents.search", "SAFE", "Study", lambda db, a, p: search(db, str(a.get("query", "")), p)),
    Tool("github.inspect", "SAFE", "GitHub", github_inspect),
    Tool("report.create", "MODERATE", "Research", report_create),
]:
    registry.register(tool)

AGENTS = [
    ("Software Engineer", "Arquitectura y planificación de software"),
    ("GitHub", "Metadatos y README de repositorios"),
    ("DevOps", "Infraestructura y despliegue"),
    ("Research", "Síntesis e informes"),
    ("Study", "Apuntes y planes de estudio"),
    ("Productivity", "Tareas y prioridades"),
    ("Email", "Correo"),
    ("Calendar", "Agenda"),
    ("Automation", "Automatizaciones"),
    ("Game Dev", "Diseño y desarrollo de videojuegos"),
    ("Security", "Revisión defensiva"),
    ("File", "Documentos e indexación"),
]

def project_list(db, args, project_id):
    rows = db.scalars(select(Item).where(Item.kind == "projects").order_by(Item.created_at.desc())).all()
    return [{"id": row.id, "title": row.title, "due": row.data.get("due", ""), "status": row.data.get("status", "PLANNING")}
            for row in rows if (not project_id or row.id == project_id)
            and (not args.get("pending", True) or row.data.get("status") not in {"DONE", "COMPLETED", "CANCELLED", "ARCHIVED"})]


registry.register(Tool("projects.list", "SAFE", "Productivity", project_list))


def project_summary(db, args, project_id):
    project_id = project_id or args.get("project_id")
    project = db.get(Item, project_id) if project_id else None
    if not project or project.kind != "projects":
        raise ValueError("Selecciona un proyecto para consultar su resumen.")
    tasks = db.scalars(select(Item).where(Item.kind == "tasks", Item.data["project_id"].as_string() == project_id)).all()
    states = {}
    for task in tasks:
        status = task.data.get("status", "TODO")
        states[status] = states.get(status, 0) + 1
    decisions = db.scalars(select(Item).where(Item.kind == "artifacts", Item.data["project_id"].as_string() == project_id,
                                            Item.data["type"].as_string() == "decision").order_by(Item.created_at.desc()).limit(10)).all()
    return {"id": project.id, "title": project.title, "objective": project.data.get("description", ""),
            "task_counts": states, "next_tasks": task_list(db, {}, project_id)[:5],
            "decisions": [{"title": row.title, "content": row.data["description"][:1000]} for row in decisions]}


def decision_create(db, args, project_id):
    result = report_create(db, args, project_id)
    row = db.get(Item, result["id"])
    row.data = row.data | {"type": "decision"}
    return result


registry.register(Tool("projects.summary", "SAFE", "Productivity", project_summary))
registry.register(Tool("decisions.create", "MODERATE", "Research", decision_create))
register_integrations(registry, Tool)
register_workspace_tools(registry, Tool)
register_item_tools(registry, Tool)
register_schedule_tools(registry, Tool)
