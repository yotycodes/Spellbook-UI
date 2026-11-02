import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "standalone"))
from lib_pl.krita import suggest_style, to_krita
import server
from starlette.testclient import TestClient


def test_strips_quality_meta_and_loras():
    p = ("score_9, score_8_up, source_anime, masterpiece, best quality, <lora:zackary911_v2_IL:0.7>, 1girl, "
         "red hair, (smile:1.2), absurdres BREAK cowboy shot, newest")
    out, neg, style, notes = to_krita(p, "easynegative, worst quality, bad hands", base="Pony")
    assert out == "1girl, red hair, (smile:1.2), cowboy shot"
    assert neg == "worst quality, bad hands"
    assert to_krita("1girl", "score_6, score_5, score_4, bad hands")[1] == "bad hands"
    assert any("zackary911_v2_IL @ 0.7" in n for n in notes) and any("Pony" in n for n in notes)


def test_style_suggestions():
    assert suggest_style("1girl, chibi, smile") == "Chibi · Toon"
    assert suggest_style("1girl, plump, wide hips") == "Curvy · Toon Pin-up"
    assert suggest_style("1girl, plump, nude", nsfw="X") == "NSFW · Boudoir Curvy (adult)"
    assert suggest_style("1girl, retro, 1950s") == "Toon · Retro Pin-up (1950s)"
    assert suggest_style("photo, 25 year old woman").startswith("Model · RealVis")
    assert suggest_style("1girl, sword") == "Model · WAI Anime"


def test_krita_open_persists_metadata(tmp_path, monkeypatch):
    img_file = tmp_path / "20261023-120000-101.png"
    img_file.write_bytes(b"fake png")
    meta_file = tmp_path / "20261023-120000-101.json"
    meta_file.write_text(json.dumps({"name": img_file.name, "seed": 42}))

    monkeypatch.setattr(server.gen, "_path", lambda name: str(img_file))
    monkeypatch.setattr(server, "_bridge", lambda path, payload, timeout=15: {
        "ok": True, "name": "Untitled.kra", "size": [1024, 1024], "resolution": 300, "color_depth": "U8"
    })

    client = TestClient(server.app)
    resp = client.post("/api/krita/open", json={"gen_name": img_file.name})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # Validate metadata in sidecar
    saved_meta = json.loads(meta_file.read_text())
    assert "krita" in saved_meta
    assert saved_meta["krita"]["document"] == "Untitled.kra"
    assert saved_meta["krita"]["size"] == [1024, 1024]
    assert saved_meta["krita"]["resolution"] == 300


def test_krita_image_persists_layer_modes(tmp_path, monkeypatch):
    img_file = tmp_path / "20261023-120000-102.png"
    img_file.write_bytes(b"fake png")
    meta_file = tmp_path / "20261023-120000-102.json"
    meta_file.write_text(json.dumps({"name": img_file.name, "seed": 99}))

    monkeypatch.setattr(server.gen, "_path", lambda name: str(img_file))
    monkeypatch.setattr(server, "_bridge", lambda path, payload, timeout=12: {
        "ok": True, "layer": "Ref · 20261023-120000-102.png", "modes": ["reference"]
    })

    client = TestClient(server.app)
    resp = client.post("/api/krita/image", json={"gen_name": img_file.name, "modes": ["reference"]})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    saved_meta = json.loads(meta_file.read_text())
    assert "krita" in saved_meta
    assert "Ref · 20261023-120000-102.png" in saved_meta["krita"]["sent_layers"]
    assert "reference" in saved_meta["krita"]["modes"]


# ---- graceful degradation without Krita --------------------------

DEAD_BRIDGE = "http://127.0.0.1:1"          # nothing listens on TCP/1


def test_krita_status_offline(monkeypatch):
    monkeypatch.setattr(server, "KRITA_BRIDGE", DEAD_BRIDGE)
    client = TestClient(server.app)
    r = client.get("/api/krita/status").json()
    assert r == {"online": False, "document": False}


def test_krita_prompt_offline_friendly_error(monkeypatch):
    monkeypatch.setattr(server, "KRITA_BRIDGE", DEAD_BRIDGE)
    client = TestClient(server.app)
    r = client.post("/api/krita/prompt", json={"prompt": "1girl, standing"}).json()
    assert r["ok"] is False
    assert "Krita isn't reachable" in r["error"]


def test_krita_styles_dir_absent(monkeypatch, tmp_path):
    """No Krita (no styles folder): meta lists zero styles, no crash."""
    monkeypatch.setattr(server, "KRITA_STYLES_DIR", str(tmp_path / "no-such-dir"))
    assert server.krita_styles() == []
    client = TestClient(server.app)
    assert client.get("/api/meta").json()["krita_styles"] == []

