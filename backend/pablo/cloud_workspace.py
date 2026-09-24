"""Cloud file snapshots. One instance and worker; local installs are unaffected."""
import hashlib
import os
import tempfile
from functools import wraps
from sqlalchemy import select
from .db import WorkspaceFile
MAX_TOTAL = 50_000_000
MAX_FILES = 500
MAX_FILE = 5_000_000


def cloud_view(function):
    """Read a committed snapshot, including during rolling deploy overlap."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        if os.getenv("PABLO_CLOUD") != "true":
            return function(*args, **kwargs)
        from .workspace_tools import workspace_override
        from .db import DB
        with tempfile.TemporaryDirectory(prefix="pablo-view-") as folder:
            token = workspace_override.set(folder)
            try:
                with DB() as db:
                    restore(db)
                return function(*args, **kwargs)
            finally:
                workspace_override.reset(token)
    return wrapped


def snapshot(db):
    from .workspace_tools import workspace_root, _walk, _relative
    files = {}
    total = 0
    for path in _walk(workspace_root(), limit=MAX_FILES + 1):
        if path.stat().st_size > MAX_FILE:
            raise ValueError("El archivo supera el límite de 5 MB del Workspace en la nube.")
        content = path.read_bytes()
        total += len(content)
        if total > MAX_TOTAL or len(files) >= MAX_FILES:
            raise ValueError("Workspace ha alcanzado su límite: 50 MB o 500 archivos. Descarga y libera espacio.")
        files[_relative(path)] = content
    old = {row.path: row for row in db.scalars(select(WorkspaceFile))}
    for path, content in files.items():
        checksum = hashlib.sha256(content).hexdigest()
        row = old.pop(path, None)
        if row is None:
            db.add(WorkspaceFile(path=path, content=content, checksum=checksum))
        elif row.checksum != checksum:
            row.content, row.checksum = content, checksum
    for row in old.values():
        db.delete(row)
    db.flush()


def checkpoint(db):
    if os.getenv("PABLO_CLOUD") == "true":
        snapshot(db)


def restore(db):
    from .workspace_tools import workspace_path
    rows = list(db.scalars(select(WorkspaceFile)))
    if len(rows) > MAX_FILES or sum(len(row.content) for row in rows) > MAX_TOTAL:
        raise ValueError("El Workspace guardado supera el límite permitido.")
    validated = []
    for row in rows:
        path = workspace_path(row.path)
        if len(row.content) > MAX_FILE or hashlib.sha256(row.content).hexdigest() != row.checksum:
            raise ValueError("No se pudo verificar un archivo guardado de Workspace.")
        validated.append((path, row.content))
    for path, content in validated:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(content)
