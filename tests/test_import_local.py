"""Import: PNG generation-info import, CSV sidecar, merge/dedupe, server endpoints."""
import csv as _csv
import io
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "standalone"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib_pl.import_local import (merge_records, parse_generation_info, parse_resources,
                                record_from_png, records_from_csv, unique_id, scrape_folder,
                                _base_from_model)


def test_parse_generation_info_basic():
    txt = ("a knight in ruins, sunbeam\n"
           "Negative prompt: blurry, watermark\n"
           "Steps: 28, Sampler: DPM++ 2M Karras, CFG scale: 6.5, Seed: 42, Size: 832x1216, Clip skip: 2, "
           "Model: someXL_v1 [abc123]")
    prompt, neg, params = parse_generation_info(txt)
    assert prompt == "a knight in ruins, sunbeam"
    assert neg == "blurry, watermark"
    assert params["Steps"] == "28"
    assert params["CFG scale"] == "6.5"
    assert params["Size"] == "832x1216"
    assert params["Clip skip"] == "2"
    # commas inside values survive: 'Karras' belongs to the Sampler value, not a new key
    assert "Karras" in params["Sampler"]


def test_parse_generation_info_without_settings_returns_prompt():
    prompt, neg, params = parse_generation_info("just a prompt, no params")
    assert prompt == "just a prompt, no params"
    assert params == {}


def test_record_from_png(tmp_path):
    from PIL import Image, PngImagePlugin
    info = PngImagePlugin.PngInfo()
    info.add_text("parameters", "a witch brewing, ember light\nNegative prompt: blurry\n"
                                "Steps: 30, Sampler: Euler a, CFG scale: 5, Size: 832x1216")
    p = tmp_path / "witch.png"
    Image.new("RGB", (32, 50), (8, 8, 8)).save(p, pnginfo=info)
    rec, reason = record_from_png(str(p))
    assert rec is not None
    assert rec["prompt"] == "a witch brewing, ember light"
    assert rec["neg"] == "blurry"
    assert rec["steps"] == 30
    assert rec["cfg"] == 5.0
    assert rec["size"] == "832x1216"
    assert rec["source"] == "png"
    assert rec["img"] == str(p)


def test_record_from_png_without_generation_info(tmp_path):
    from PIL import Image
    p = tmp_path / "plain.png"
    Image.new("RGB", (10, 10)).save(p)
    rec, reason = record_from_png(str(p))
    assert rec is None


def test_record_from_comfy_workflow(tmp_path):
    from PIL import Image, PngImagePlugin
    info = PngImagePlugin.PngInfo()
    info.add_text("prompt", json.dumps({
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "comfy knight, dusk"}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "low quality"}},
        "3": {"class_type": "KSampler", "inputs": {"sampler_name": "euler_ancestral", "scheduler": "karras", "steps": 22, "cfg": 4.5}},
    }))
    p = tmp_path / "comfy.png"
    Image.new("RGB", (16, 16)).save(p, pnginfo=info)
    rec, _ = record_from_png(str(p))
    assert rec["prompt"] == "comfy knight, dusk"
    assert rec["neg"] == "low quality"
    assert rec["steps"] == 22
    assert rec["cfg"] == 4.5
    assert "Euler" in rec["sampler"] or rec["sampler"]


def test_records_from_csv_sidecar_style():
    body = ("id,url,base,rating,reactions,prompt,negative,sampler,steps,cfg,size,clip_skip,resources\n"
            '9173928,https://civitai.com/images/9173928,SDXL 1.0,Soft,36255,"knight test","blurry",DPM++ 2M,45,5,832x1216,2,'
            '"LORA: Some Lora (v1.0) @0.65 | Checkpoint: WildCardX-XL (FUSION OG) | TextualInversion: EasyNegative"\n')
    rows = records_from_csv(io.TextIOWrapper(io.BytesIO(body.encode()), encoding="utf-8-sig"))
    assert len(rows) == 1
    r = rows[0]
    assert r["id"] == 9173928 and r["nsfw"] == "Soft" and r["react"] == 36255
    assert r["res"] and r["res"][0]["t"] == "LORA" and r["res"][0]["n"] == "Some Lora" and r["res"][0]["w"] == 0.65
    assert r["res"][1]["t"] == "Checkpoint"
    assert r["res"][2]["t"] == "TextualInversion"


def test_parse_resources_missing_completion_prefixes():
    res = parse_resources("LORA: Alpha Beta (v1.1) @0.8 | LORA: Gamma Delta")
    assert [x["n"] for x in res] == ["Alpha Beta", "Gamma Delta"]
    assert res[0]["w"] == 0.8


def test_merge_records_dedupe_and_allocation(tmp_path):
    n, dest = merge_records(str(tmp_path), [
        {"id": 500, "prompt": "alpha knight", "nsfw": "None", "base": "Illustrious"},
        {"id": 501, "prompt": "beta knight", "nsfw": "None", "base": "Illustrious"},
        {"id": 500, "prompt": "alpha knight", "nsfw": "None", "base": "Illustrious"},  # dupe id
        {"prompt": "beta knight", "nsfw": "None"},  # dupe by prompt text, id allocated later
    ])
    assert n == 2
    rows = json.load(open(tmp_path / "all-prompts.json"))
    assert {r["id"] for r in rows} == {500, 501}

    # a second merge extends; prompt-text dedupe keeps re-imports idempotent
    n2, _ = merge_records(str(tmp_path), [{"prompt": "totally new wanderer record"}])
    assert n2 == 1
    rows2 = json.load(open(tmp_path / "all-prompts.json"))
    ids = [r["id"] for r in rows2]
    assert len(ids) == len(set(ids)), f"ids must stay unique: {sorted(ids)}"


def test_unique_id_avoids_collisions():
    used = set()
    a = unique_id(used, "one")
    b = unique_id(used, "two")
    assert a != b and a > 0


def test_base_from_model():
    assert _base_from_model("Illustrious-XL v1.3") == "Illustrious"
    assert _base_from_model("noobAI-vpred v1") == "NoobAI"
    assert _base_from_model("Pony Diffusion V6 XL") == "Pony"
    assert _base_from_model("illusXL_v1") == "Illustrious"
    assert _base_from_model("weirdModel") == "Other"


def test_scrape_folder_finds_png(tmp_path):
    from PIL import Image
    (tmp_path / "sub").mkdir()
    Image.new("RGB", (5, 5)).save(tmp_path / "a.png")
    Image.new("RGB", (5, 5)).save(tmp_path / "sub" / "b.png")
    Image.new("RGB", (5, 5)).save(tmp_path / "c.jpg")
    files = scrape_folder(str(tmp_path))
    names = [os.path.basename(f) for f in files]
    assert "a.png" in names and "b.png" in names and "c.jpg" not in names


# ------------------------------------------------------------------ server endpoints
def _client():
    from starlette.testclient import TestClient
    from server import app
    return TestClient(app)


def test_search_empty_library_is_structured_not_500(monkeypatch):
    from server import S
    real = S["library_path"]
    monkeypatch.setitem(S, "library_path", str(__import__("tempfile").mkdtemp() + "/missing"))
    c = _client()
    try:
        r = c.get("/api/search")
        assert r.status_code == 200
        d = r.json()
        assert d["items"] == [] and "library_error" in d
    finally:
        monkeypatch.setitem(S, "library_path", real)


def test_starter_shelf_endpoint_imports_runnable(tmp_path, monkeypatch):
    from server import S
    import server
    real = S["library_path"]
    monkeypatch.setitem(S, "library_path", str(tmp_path / "lib"))
    monkeypatch.setattr(server, "_existing_ids", lambda: set())
    c = _client()
    try:
        r = c.post("/api/library/starter-shelf")
        assert r.status_code == 200
        assert r.json()["imported"] == 50
        rows = json.load(open(tmp_path / "lib" / "all-prompts.json"))
        assert len(rows) == 50
        # all-recipe shelf: 100% original content
        assert all(x.get("source") == "spellbook" for x in rows)
        assert all(x["id"] < 0 for x in rows)
        # runnability promise: SFW, no LoRA/embedding requirements, Illustrious base
        for x in rows:
            assert x["nsfw"] == "None"
            assert x.get("base") == "Illustrious"
            assert not [l for l in (x.get("res") or [])
                        if (l.get("t") or "").lower() in ("lora", "locon", "dora")]
            assert x.get("themes")
    finally:
        monkeypatch.setitem(S, "library_path", real)


def test_export_endpoint_requires_library(tmp_path, monkeypatch):
    from server import S
    real = S["library_path"]
    monkeypatch.setitem(S, "library_path", str(tmp_path / "nope"))
    c = _client()
    try:
        assert c.get("/api/library/export.json").status_code == 404
        json.dump([{"id": 1, "prompt": "x"}], open(tmp_path / "nope_all.json", "w"))
        (tmp_path / "nope").mkdir(exist_ok=True)
        json.dump([{"id": 1, "prompt": "x"}], open(tmp_path / "nope" / "all-prompts.json", "w"))
        r = c.get("/api/library/export.json")
        assert r.status_code == 200
        assert json.load(io.BytesIO(r.content))[0]["prompt"] == "x"
    finally:
        monkeypatch.setitem(S, "library_path", real)
