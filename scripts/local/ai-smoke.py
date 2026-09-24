"""Opt-in real Ollama smoke test, with an isolated database and no personal data."""
import os
import sys
import tempfile
import time
from pathlib import Path

root = Path(__file__).resolve().parents[2]
os.chdir(root)
sys.path.insert(0, str(root / "backend"))

with tempfile.TemporaryDirectory(prefix="pablo-ai-qa-") as folder:
    os.environ.update(DATABASE_URL="sqlite:///" + str(Path(folder) / "test.db"),
                      AI_BASE_URL="http://127.0.0.1:11434/v1", AI_API_KEY="ollama",
                      AI_MODEL=os.environ.get("PABLO_TEST_MODEL", "llama3.2:1b"), AI_EMBED_MODEL="")
    from alembic import command
    from alembic.config import Config
    from fastapi.testclient import TestClient
    from pablo.db import DB, Run, engine
    from pablo.main import app
    from pablo.worker import process

    command.upgrade(Config("backend/alembic.ini"), "head")
    try:
        with TestClient(app) as client:
            client.headers["X-Pablo-Request"] = "1"
            client.post("/api/v1/auth/setup", json={"name": "QA", "password": "Temporary-QA-password-123"}).raise_for_status()
            conversation = None
            for goal in ["Me llamo Lucía. Responde solamente: Hola Lucía.", "¿Cómo me llamo? Responde brevemente."]:
                start = time.monotonic()
                response = client.post("/api/v1/commands", json={"goal": goal, "conversation_id": conversation})
                response.raise_for_status()
                row = response.json()
                conversation = row["conversation_id"]
                process(row["id"])
                with DB() as db:
                    run = db.get(Run, row["id"])
                    assert run.status == "COMPLETED", run.result
                    assert "lucía" in run.result.casefold(), run.result
                    print(f"PASS ASK ({time.monotonic()-start:.1f}s): {run.result}", flush=True)
            from pablo.providers import CompatibleProvider
            start = time.monotonic()
            plan, _ = CompatibleProvider().plan("Propón crear una tarea titulada Repasar Python. No la ejecutes.", "PLAN", {})
            assert len(plan.steps) == 1 and plan.steps[0].tool == "tasks.create", plan
            assert plan.steps[0].arguments.get("title") == "Repasar Python", plan
            print(f"PASS PLAN ({time.monotonic()-start:.1f}s): {plan.model_dump()}", flush=True)
    finally:
        engine.dispose()
