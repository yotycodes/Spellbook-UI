import socket
import sys
import os

# Ensure standalone directory is in path for standalone imports if needed
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "standalone"))

from server import _is_port_in_use, _find_available_port, app
from gen import _keep_awake, _worker
from starlette.testclient import TestClient


def test_health_endpoint():
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["app"] == "spellbook"


def test_port_detection():
    # Bind a temporary local socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        busy_port = s.getsockname()[1]

        # The bound port must report in use
        assert _is_port_in_use(busy_port) is True

        # Finding available port starting at busy_port should return an alternative
        next_port = _find_available_port(busy_port, max_attempts=5)
        assert next_port != busy_port
        assert _is_port_in_use(next_port) is False


def test_keep_awake_atexit_safe():
    # Calling _keep_awake(False) when worker caffeinate is None shouldn't error
    _worker["caffeinate"] = None
    _keep_awake(False)
    assert _worker.get("caffeinate") is None


def test_collection_delete_returns_ids_and_restore_roundtrip(tmp_path, monkeypatch):
    import json as json_mod
    from server import FAV, app

    # point the module-level Favorites at a temp file so real app data is untouched
    real_path = FAV.path
    monkeypatch.setattr(FAV, "path", str(tmp_path / "fav.json"))
    FAV.data["collections"]["Test Undo"] = [11, 22]
    FAV._save()

    client = TestClient(app)
    try:
        r = client.post("/api/collections/delete", json={"name": "Test Undo"})
        assert r.status_code == 200
        body = r.json()
        assert body["ids"] == [11, 22]  # membership travels with the delete so Undo can be exact
        assert "Test Undo" not in body["collections"]
        saved = json_mod.load(open(tmp_path / "fav.json"))
        assert "Test Undo" not in saved["collections"]

        r2 = client.post("/api/collections/restore", json={"name": "Test Undo", "ids": [11, 22]})
        assert r2.status_code == 200
        assert "Test Undo" in r2.json()["collections"]
        saved = json_mod.load(open(tmp_path / "fav.json"))
        assert FAV.ids("Test Undo") == {11, 22}
    finally:
        FAV.data["collections"].pop("Test Undo", None)
        monkeypatch.setattr(FAV, "path", real_path)
