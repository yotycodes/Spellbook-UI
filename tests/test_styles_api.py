"""Styles manager backend: /api/styles CRUD + validation. Patching pattern: kstyles dirs are module
globals, so tests repoint them (and blank gen's styles cache) and restore — hermetic on any machine."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "standalone"))
from lib_pl import kstyles as _kstyles
import gen
import server
from starlette.testclient import TestClient

FORM = {"name": "Test · Bold", "checkpoint": "waiIllustriousSDXL_v170.safetensors",
        "loras": [{"name": "zack_IL.safetensors", "strength": 0.7}],
        "style_prompt": "bold outline, {prompt}", "negative": "blurry, text",
        "sampler": "Euler a", "scheduler": "Karras", "steps": 28, "cfg": 5.5, "clip_skip": 2}


def _patch_dirs(monkeypatch, tmp_path):
    def patch():
        monkeypatch.setattr(_kstyles, "STYLES_DIR", str(tmp_path / "styles"))
        monkeypatch.setattr(_kstyles, "FALLBACK_DIR", None)
        _reset()
    def _reset():
        gen._styles.update(list=[], mtime=None)
    monkeypatch.setattr(server, "STYLES_DIR", str(tmp_path / "styles"))
    patch()
    return patch, _reset


def _client():
    return TestClient(server.app)


def test_create_list_update_round_trip(tmp_path, monkeypatch):
    patch, _reset = _patch_dirs(monkeypatch, tmp_path)
    try:
        c = _client()
        r = c.post("/api/styles", json=FORM)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] and d["file"] == "test-bold.json" and d["name"] == "Test · Bold"
        # the row immediately shows up editable
        row = next(s for s in d["styles"] if s["name"] == "Test · Bold")
        assert row["editable"] and row["checkpoint"] == "waiIllustriousSDXL_v170.safetensors"
        assert [list(x) for x in row["loras"]] == [["zack_IL", 0.7]] and row["sampler"] == "Euler a" and row["scheduler"] == "Karras"
        on_disk = json.load(open(os.path.join(tmp_path, "styles", d["file"])))
        assert on_disk["version"] == 2 and on_disk["checkpoints"] == [FORM["checkpoint"]]
        assert on_disk["loras"] == [{"name": "zack_IL.safetensors", "strength": 0.7, "enabled": True}]
        # exact round trip via vendor keys
        assert on_disk["spellbook_sampler"] == "euler_ancestral" and on_disk["spellbook_scheduler"] == "karras"

        # update in place (same name)
        r2 = c.post(f"/api/styles/{d['file']}", json={**FORM, "steps": 40})
        assert r2.status_code == 200 and r2.json()["file"] == "test-bold.json"
        assert next(s for s in r2.json()["styles"] if s["file"] == "test-bold.json")["steps"] == 40
        assert len(os.listdir(os.path.join(tmp_path, "styles"))) == 1

        # rename moves the file
        r3 = c.post(f"/api/styles/{d['file']}", json={**FORM, "name": "Renamed · Bold"})
        files = sorted(os.listdir(os.path.join(tmp_path, "styles")))
        assert files == ["renamed-bold.json"], files
        assert r3.json()["file"] == "renamed-bold.json"
    finally:
        _reset()


def test_validation_errors(tmp_path, monkeypatch):
    patch, _reset = _patch_dirs(monkeypatch, tmp_path)
    try:
        c = _client()
        for bad, code in (({**FORM, "name": " "}, 400), ({**FORM, "sampler": "Turbo Alpha"}, 400),
                          ({**FORM, "steps": "bogus"}, 400), ({}, 400)):
            r = c.post("/api/styles", json=bad)
            assert r.status_code == code, (bad, r.status_code, r.text)
        # bad prompt marker auto-appended instead of rejected
        r = c.post("/api/styles", json={**FORM, "style_prompt": "bold outline"})
        assert r.status_code == 200
        assert "{prompt}" in json.load(open(os.path.join(tmp_path, "styles", r.json()["file"])))["style_prompt"]

        # duplicate name -> 409 on create
        r = c.post("/api/styles", json=FORM)
        assert r.status_code == 409
        # clamping: absurd numbers come back sane
        r = c.post("/api/styles", json={**FORM, "name": "Clamped", "steps": 9999, "cfg": 90, "strength": 0})
        row = next(s for s in r.json()["styles"] if s["name"] == "Clamped")
        assert row["steps"] == 150 and row["cfg"] == 20.0
    finally:
        _reset()


def test_delete_endpoint_and_readonly_guard(tmp_path, monkeypatch):
    patch, _reset = _patch_dirs(monkeypatch, tmp_path)
    krita = tmp_path / "krita"
    krita.mkdir()
    json.dump({"name": "Krita Side"}, open(krita / "k.json", "w"))
    try:
        monkeypatch.setattr(_kstyles, "FALLBACK_DIR", str(krita))
        c = _client()
        r = c.post("/api/styles", json=FORM)
        fn = r.json()["file"]
        # the Krita-origin row is visible but locked
        rows = {s["name"]: s for s in c.get("/api/styles").json()["styles"]}
        assert rows["Krita Side"]["origin"] == "krita" and not rows["Krita Side"]["editable"]
        assert c.delete("/api/styles/nope.json").status_code == 404
        assert c.delete(f"/api/styles/{fn}").status_code == 200
        assert not os.path.exists(os.path.join(tmp_path, "styles", fn))
        names = [s["name"] for s in c.get("/api/styles").json()["styles"]]
        assert "Test · Bold" not in names and "Krita Side" in names
        # editing a missing file -> 404; deleting/overwriting a Krita read-only file -> guarded
        assert c.post(f"/api/styles/{fn}", json=FORM).status_code == 404
        assert c.delete("/api/styles/k.json").status_code == 400
    finally:
        _reset()
