import hashlib
import json
from pathlib import Path

import pytest

from pablo.cloud_config import configure
from pablo.cloud_workspace import restore, snapshot
from pablo.db import DB, WorkspaceFile


def test_restart_restores_two_websites(client, tmp_path, monkeypatch):
    first = tmp_path / "first"
    first.mkdir()
    monkeypatch.setenv("PABLO_WORKSPACE_ROOT", str(first))
    from pablo.workspace_tools import code_scaffold
    for name in ("Restaurante", "Portfolio"):
        code_scaffold(None, {"name": name, "kind": "web", "html": "<h1>" + name + "</h1>"}, None)
    with DB() as db:
        snapshot(db)
        db.commit()
    second = tmp_path / "after-restart"
    second.mkdir()
    monkeypatch.setenv("PABLO_WORKSPACE_ROOT", str(second))
    with DB() as db:
        restore(db)
    assert "Restaurante" in (second / "restaurante/index.html").read_text()
    assert "Portfolio" in (second / "portfolio/index.html").read_text()
    assert len(list(second.rglob("*.*"))) == 12


def test_snapshot_rollback_keeps_last_committed_files(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PABLO_WORKSPACE_ROOT", str(tmp_path))
    path = tmp_path / "note.txt"
    path.write_text("saved")
    with DB() as db:
        snapshot(db)
        db.commit()
    path.write_text("failed")
    with DB() as db:
        snapshot(db)
        db.rollback()
    with DB() as db:
        assert db.get(WorkspaceFile, "note.txt").content == b"saved"


def test_restore_rejects_traversal_before_writing(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PABLO_WORKSPACE_ROOT", str(tmp_path))
    with DB() as db:
        db.add(WorkspaceFile(path="../outside.txt", content=b"x", checksum=hashlib.sha256(b"x").hexdigest()))
        db.commit()
        with pytest.raises(ValueError):
            restore(db)
    assert not (tmp_path.parent / "outside.txt").exists()


def test_cloud_workspace_download_survives_temporary_cleanup(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PABLO_WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / "web.html").write_text("<h1>Saved</h1>")
    with DB() as db:
        snapshot(db)
        db.commit()
    (tmp_path / "web.html").unlink()
    monkeypatch.setenv("PABLO_CLOUD", "true")
    assert client.get("/api/v1/workspace/download", params={"path": "web.html"}).content == b"<h1>Saved</h1>"
    preview = client.get("/api/v1/workspace/preview/web.html")
    assert preview.status_code == 200
    assert "Saved" in preview.text
    assert "allow-same-origin" not in preview.headers["content-security-policy"]


def test_cloud_setup_is_not_public(client, monkeypatch):
    monkeypatch.setenv("PABLO_CLOUD", "true")
    assert client.post("/api/v1/auth/setup", json={"name": "Stranger", "password": "Password123456"}).status_code == 403


def test_cloud_refuses_ephemeral_database(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///temp.db")
    with pytest.raises(ValueError, match="SQLite"):
        configure()


def test_cloud_config_requires_https_and_stable_key(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@example.com/postgres")
    monkeypatch.setenv("APP_ORIGIN", "http://example.com")
    with pytest.raises(ValueError, match="HTTPS"):
        configure()
    monkeypatch.setenv("APP_ORIGIN", "https://example.com")
    monkeypatch.setenv("PABLO_CLOUD_MASTER_KEY", "x" * 40)
    monkeypatch.setenv("PABLO_OWNER_PASSWORD", "test-long-password")
    for key in ("PABLO_CLOUD", "COOKIE_SECURE", "PABLO_SECRET_KEY"):
        monkeypatch.setenv(key, "")
    configure()
    import os

    from cryptography.fernet import Fernet
    cipher = Fernet(os.environ["PABLO_SECRET_KEY"])
    assert cipher.decrypt(cipher.encrypt(b"secret")) == b"secret"
    assert os.environ["COOKIE_SECURE"] == "true"


def test_mobile_assets_are_served_as_files(client):
    manifest = client.get("/manifest.webmanifest")
    assert manifest.status_code == 200
    assert manifest.json()["display"] == "standalone"
    worker = client.get("/sw.js")
    assert "javascript" in worker.headers["content-type"]
    assert worker.headers["cache-control"] == "no-cache"
    assert "caches.open" not in worker.text


def test_migration_preserves_ids_and_reencrypts_credentials(client, tmp_path, monkeypatch):
    import importlib.util
    import sys

    from cryptography.fernet import Fernet
    from sqlalchemy import create_engine, delete

    from pablo.db import Base, Item, Owner
    from pablo.integrations import Integration
    source = tmp_path / "source"
    source.mkdir()
    (source / "generated").mkdir()
    (source / "generated/page.html").write_text("<h1>Original</h1>")
    old_key, new_key = Fernet.generate_key(), Fernet.generate_key()
    (source / ".env").write_text("PABLO_SECRET_KEY=" + old_key.decode())
    source_engine = create_engine("sqlite:///" + (source / "pablo.db").as_posix())
    Base.metadata.create_all(source_engine)
    with source_engine.begin() as conn:
        conn.execute(Owner.__table__.insert(), {"id": 1, "name": "Original", "password": "hash", "settings": {}})
        conn.execute(Item.__table__.insert(), {"id": "keep-id", "kind": "tasks", "title": "Keep title", "data": {}})
        conn.execute(Integration.__table__.insert(), {"id": "google", "config": {},
                     "encrypted": Fernet(old_key).encrypt(b'{"access_token":"synthetic"}').decode()})
    source_engine.dispose()
    with DB() as db:
        for table in reversed(Base.metadata.sorted_tables):
            if table.name != "users":
                db.execute(delete(table))
        db.commit()
    config = tmp_path / "private.env"
    config.write_text("APP_ORIGIN=https://example.test")
    monkeypatch.setenv("APP_ORIGIN", "https://example.test")
    monkeypatch.setenv("PABLO_SECRET_KEY", new_key.decode())
    from pablo import cloud_config
    monkeypatch.setattr(cloud_config, "configure", lambda: None)
    monkeypatch.setattr(sys, "argv", ["migrate", "--source", str(source), "--config", str(config), "--apply"])
    path = Path("scripts/cloud/migrate.py")
    spec = importlib.util.spec_from_file_location("migration_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.main()
    with DB() as db:
        assert db.get(Item, "keep-id").title == "Keep title"
        assert db.get(Owner, 1).name == "Original"
        assert json.loads(Fernet(new_key).decrypt(db.get(Integration, "google").encrypted))["access_token"] == "synthetic"
        assert db.get(WorkspaceFile, "page.html").content == b"<h1>Original</h1>"
    with pytest.raises(ValueError, match="ya contiene datos"):
        module.main()
