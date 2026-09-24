"""Copy a stopped local installation to an empty cloud database.

Usage: python scripts/cloud/migrate.py --source C:/path/to/local/project
       --config C:/private/cloud.env --apply
The private config contains DATABASE_URL, APP_ORIGIN, PABLO_CLOUD_MASTER_KEY and
PABLO_OWNER_PASSWORD. Never commit it. Secrets are re-encrypted, never printed.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, inspect, select, delete


def read_config(path):
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    source = args.source.resolve()
    if not (source / "pablo.db").is_file():
        raise ValueError("No se encuentra la base de datos local.")
    if (source / ".local/runtime.json").exists():
        raise ValueError("Cierra el servidor local con DETENER o run.py --stop antes de migrar.")
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "backend"))
    config = read_config(args.config)
    allowed = {"DATABASE_URL", "APP_ORIGIN", "PABLO_CLOUD_MASTER_KEY", "PABLO_OWNER_PASSWORD"}
    if set(config) - allowed:
        raise ValueError("El archivo privado contiene variables desconocidas.")
    os.environ.update(config)
    from pablo.cloud_config import configure
    configure()
    from pablo.db import Base, DB, Owner, WorkspaceFile
    from pablo import integrations  # Register connector tables in metadata.
    from pablo.cloud_workspace import snapshot
    from pablo.workspace_tools import workspace_override
    local = read_config(source / ".env") if (source / ".env").exists() else {}
    key = local.get("PABLO_SECRET_KEY", "").encode()
    if not key:
        key_path = Path(local.get("PABLO_SECRET_KEY_FILE", ".pablo-secrets.key"))
        key_path = key_path if key_path.is_absolute() else source / key_path
        key = key_path.read_bytes()
        if key.startswith(b"DPAPI:"):
            key = integrations._windows_protect(key[6:], decrypt=True)
    old_cipher, new_cipher = Fernet(key), Fernet(os.environ["PABLO_SECRET_KEY"].encode())
    # SQLite read-only connection, with one consistent read transaction.
    source_url = "sqlite:///file:" + (source / "pablo.db").as_posix() + "?mode=ro&uri=true"
    src = create_engine(source_url)
    skipped = {"sessions", "oauth_states", "runtime_status", "workspace_files"}
    records = {}
    with src.connect() as conn:
        conn.exec_driver_sql("BEGIN")
        present = set(inspect(conn).get_table_names())
        for table in Base.metadata.sorted_tables:
            if table.name in skipped or table.name not in present:
                continue
            rows = [dict(row) for row in conn.execute(select(table)).mappings()]
            for row in rows:
                if row.get("encrypted"):
                    row["encrypted"] = new_cipher.encrypt(old_cipher.decrypt(row["encrypted"].encode())).decode()
                if table.name == "integrations" and row.get("id") == "google":
                    row["config"] = dict(row["config"], redirect_uri=os.environ["APP_ORIGIN"] + "/api/v1/integrations/google/callback")
                if table.name == "agent_runs":
                    row["lease_token"], row["lease_until"] = None, None
                    if row["status"] in {"QUEUED", "RUNNING", "WAITING_APPROVAL"}:
                        raise ValueError("Termina o cancela las ejecuciones pendientes antes de migrar.")
            records[table.name] = rows
        conn.rollback()
    with DB() as db:
        for table in Base.metadata.sorted_tables:
            if table.name not in {"users", "runtime_status", "sessions", "oauth_states"}:
                if db.execute(select(table).limit(1)).first():
                    raise ValueError("La nube ya contiene datos. No se sobrescribe ninguna instalación.")
        print("Registros preparados:", sum(len(rows) for rows in records.values()))
        if not args.apply:
            print("Validación completa. Usa --apply para realizar la transferencia.")
            return
        for table in Base.metadata.sorted_tables:
            if table.name in {"users", "sessions", "oauth_states"}:
                db.execute(delete(table))
        for table in Base.metadata.sorted_tables:
            if records.get(table.name):
                db.execute(table.insert(), records[table.name])
        token = workspace_override.set(str(source / "generated"))
        try:
            snapshot(db)
        finally:
            workspace_override.reset(token)
        db.commit()
    print("Migración terminada. Usa la URL HTTPS también desde el ordenador; no mantengas dos bases activas.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Database exceptions may contain connection strings or record payloads.
        print(str(error) if isinstance(error, ValueError) else "No se completó la migración. Revisa conexión y configuración; no se muestran credenciales.", file=sys.stderr)
        raise SystemExit(1)
