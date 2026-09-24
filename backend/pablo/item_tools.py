"""Transactional domain tools. Every mutation runs through the worker's approval gate."""
from sqlalchemy import delete, select

from .db import Chunk, Item, Owner, now
from .schemas import Record

KINDS = {"tasks", "projects", "memory", "workflows", "calendar", "documents", "artifacts", "drafts"}
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "PLANNED", "BLOCKED"}


def list_items(db, args, project_id):
    kind = args.get("kind")
    if kind not in KINDS:
        raise ValueError("Indica un tipo de elemento válido.")
    query = select(Item).where(Item.kind == kind)
    if project_id:
        query = query.where((Item.id == project_id) | (Item.data["project_id"].as_string() == project_id))
    rows = db.scalars(query.order_by(Item.created_at.desc())).all()
    if kind == "memory":
        settings = db.get(Owner, 1).settings
        rows = [r for r in rows if settings.get("memory_enabled", True)
                and r.data.get("category") in settings.get("memory_categories", [])]
    term = str(args.get("query", "")).casefold()
    return [{"id": r.id, "kind": r.kind, "title": r.title, "version": r.version, "data": r.data}
            for r in rows if term in r.title.casefold()][:100]


def resolve(db, args, project_id):
    kind = args.get("kind")
    if kind not in KINDS:
        raise ValueError("Indica el tipo de elemento.")
    query = select(Item).where(Item.kind == kind)
    if args.get("id"):
        query = query.where(Item.id == args["id"])
    elif args.get("title"):
        query = query.where(Item.title == args["title"])
    else:
        raise ValueError("Indica el ID o título exacto del elemento.")
    if project_id:
        query = query.where((Item.id == project_id) | (Item.data["project_id"].as_string() == project_id))
    rows = db.scalars(query).all()
    if len(rows) != 1:
        raise ValueError("No se encontró un único elemento. Consulta los elementos y utiliza su ID exacto.")
    row = rows[0]
    if args.get("version") is not None and row.version != args["version"]:
        raise ValueError("El elemento cambió desde que se preparó la acción. Vuelve a solicitarla.")
    return row


def validated(db, kind, values, item_id=None):
    from .main import validate_record

    if kind in {"tasks", "projects", "memory", "workflows"}:
        body = Record.model_validate(values)
        validate_record(db, body, kind, item_id)
        return body.title, body.model_dump(exclude={"title", "version"})
    if kind == "calendar":
        from .capabilities import Event, event_data, project_exists
        body = Event.model_validate(values)
        project_exists(db, body.project_id)
        return body.title, event_data(body)
    allowed = {"title", "description", "content", "project_id"}
    if set(values) - allowed:
        raise ValueError("Campos no admitidos para este elemento.")
    title = values.get("title", "")
    content = values.get("content", values.get("description", ""))
    if not isinstance(title, str) or not title.strip() or len(title) > 300:
        raise ValueError("El título debe tener entre 1 y 300 caracteres.")
    if not isinstance(content, str) or len(content) > 500000:
        raise ValueError("Contenido inválido o demasiado largo.")
    if values.get("project_id"):
        from .capabilities import project_exists
        project_exists(db, values["project_id"])
    return title, {"description": content, "project_id": values.get("project_id")}


def create_item(db, args, project_id):
    kind = args.get("kind")
    if kind not in KINDS:
        raise ValueError("Tipo de elemento no admitido.")
    values = dict(args.get("values", {}))
    values.setdefault("project_id", project_id)
    if kind == "projects":
        values.setdefault("status", "PLANNING")
    title, data = validated(db, kind, values)
    row = Item(kind=kind, title=title, data=data)
    db.add(row)
    db.flush()
    reindex(db, row)
    return {"id": row.id, "title": row.title, "kind": kind, "verified": True}


def reindex(db, row):
    if row.kind == "documents":
        from .knowledge import index
        db.execute(delete(Chunk).where(Chunk.document_id == row.id))
        count = index(db, row.id, row.data.get("description", ""))
        row.data = row.data | {"chunks": count, "status": "INDEXED"}


def update_item(db, args, project_id):
    row = resolve(db, args, project_id)
    changes = args.get("changes")
    if not isinstance(changes, dict) or not changes:
        raise ValueError("Indica los campos que deseas modificar.")
    current = {"title": row.title, **row.data}
    if row.kind in {"documents", "artifacts", "drafts"}:
        current = {k: v for k, v in current.items() if k in {"title", "description", "project_id"}}
    title, data = validated(db, row.kind, current | changes, row.id)
    row.title = title
    row.data = row.data | data if row.kind in {"documents", "artifacts", "drafts"} else data
    row.version += 1
    row.updated_at = now()
    if row.kind == "documents" and ("content" in changes or "description" in changes):
        reindex(db, row)
    db.flush()
    return {"id": row.id, "title": title, "version": row.version, "verified": True}


def delete_item(db, args, project_id):
    row = resolve(db, args, project_id)
    if row.kind == "projects":
        from .project_lifecycle import detach_project
        detach_project(db, row.id)
    if row.kind == "tasks":
        if any(row.id in r.data.get("dependencies", []) for r in db.scalars(select(Item).where(Item.kind == "tasks"))):
            raise ValueError("Otra tarea depende de esta. Modifica primero la dependencia.")
    result = {"id": row.id, "title": row.title, "deleted": True, "verified": True}
    db.execute(delete(Chunk).where(Chunk.document_id == row.id))
    db.delete(row)
    db.flush()
    return result


def register(registry, tool):
    for name, risk, function in [("list", "SAFE", list_items), ("create", "MODERATE", create_item),
                                 ("update", "MODERATE", update_item), ("delete", "HIGH", delete_item)]:
        registry.register(tool("items." + name, risk, "Productivity", function))
