"""Reset the local PABLO OS password without printing or storing it in plain text."""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_environment() -> None:
    os.chdir(ROOT)
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    os.environ.setdefault("DATABASE_URL", "sqlite:///" + str(ROOT / "pablo.db"))
    os.environ["PYTHONPATH"] = str(ROOT / "backend")
    # PYTHONPATH set at runtime does not alter sys.path of this interpreter.
    sys.path.insert(0, str(ROOT / "backend"))


def main() -> int:
    load_environment()
    from sqlalchemy import delete

    from pablo.db import DB, Owner, Session
    from pablo.security import password_hash

    print("Restablecer contraseña de PABLO OS")
    print("La contraseña se solicita solo en este equipo y no se muestra.\n")
    first = getpass.getpass("Nueva contraseña (mínimo 12 caracteres): ")
    second = getpass.getpass("Repite la nueva contraseña: ")
    if not 12 <= len(first) <= 256:
        print("Error: la contraseña debe tener entre 12 y 256 caracteres.")
        return 1
    if first != second:
        print("Error: las contraseñas no coinciden.")
        return 1

    with DB() as db:
        owner = db.get(Owner, 1)
        if owner is None:
            print("Error: todavía no existe una cuenta local. Inicia PABLO OS para crearla.")
            return 1
        owner.password = password_hash(first)
        db.execute(delete(Session))
        db.commit()
    print("Contraseña actualizada. Ya puedes iniciar PABLO OS y entrar con la nueva contraseña.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
