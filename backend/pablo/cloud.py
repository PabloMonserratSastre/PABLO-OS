"""One free web service supervises API and worker. No local .env is loaded."""
import os
import signal
import subprocess
import sys
import tempfile
import time
from .cloud_config import configure


def main():
    configure()
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text
    from .db import engine, DB, Owner
    from .schemas import Settings
    from .security import password_hash

    # This schema is not among Supabase's default publicly exposed API schemas.
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS pablo"))
        conn.execute(text("REVOKE ALL ON SCHEMA pablo FROM PUBLIC"))
    command.upgrade(Config("backend/alembic.ini"), "head")
    with DB() as db:
        if db.get(Owner, 1) is None:
            name = os.getenv("PABLO_OWNER_NAME", "Pablo")
            db.add(Owner(id=1, name=name, password=password_hash(os.environ["PABLO_OWNER_PASSWORD"]),
                         settings=Settings(name=name).model_dump()))
            db.commit()
    os.environ["PABLO_WORKSPACE_ROOT"] = tempfile.mkdtemp(prefix="pablo-cloud-")
    stopped = False
    def stop(*_):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    children = []
    try:
        children.append(subprocess.Popen([sys.executable, "-m", "pablo.worker"]))
        children.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "pablo.main:app",
                         "--host", "0.0.0.0", "--port", str(int(os.getenv("PORT", "8000")))]))
        while not stopped:
            for child in children:
                if child.poll() is not None:
                    return child.returncode or 1
            time.sleep(0.5)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
