import json
import os

import pytest

from lib_pl import kstyles
from lib_pl.kstyles import apply, load, validate


def _write(tmp_path, **kw):
    d = {"name": "Toon", "checkpoints": ["sub/novaCartoonXL_v60.safetensors"], "architecture": "illu",
         "loras": [{"name": "zack_IL.safetensors", "strength": 0.7, "enabled": True},
                   {"name": "off.safetensors", "strength": 1, "enabled": False}],
         "style_prompt": "z4ck, {prompt}, masterpiece, best quality", "negative_prompt": "3d, realistic",
         "clip_skip": 2, "sampler": "Alternative - Euler A", "sampler_steps": 28, "cfg_scale": 5.5}
    d.update(kw)
    (tmp_path / "toon.json").write_text(json.dumps(d))
    presets = tmp_path.parent / f"{tmp_path.name}-samplers.json"
    presets.write_text(json.dumps({"Alternative - Euler A": {"sampler": "euler_ancestral", "scheduler": "normal"}}))
    return load(str(tmp_path), str(presets))


def test_load_maps_to_forge_names(tmp_path):
    s = _write(tmp_path)[0]
    assert s["checkpoint"] == "novaCartoonXL_v60.safetensors"
    assert s["loras"] == [("zack_IL", 0.7)]
    assert (s["sampler"], s["scheduler"], s["steps"], s["cfg"], s["clip_skip"]) == ("Euler a", "Normal", 28, 5.5, 2)


def test_apply_wraps_prompt_adds_loras_and_dedupes(tmp_path):
    s = _write(tmp_path)[0]
    p, n = apply(s, "1girl, red hair, masterpiece", "watermark, 3d")
    assert p == "z4ck, 1girl, red hair, masterpiece, best quality, <lora:zack_IL:0.7>"
    assert n == "3d, realistic, watermark"


def test_apply_keeps_existing_lora_and_handles_no_placeholder(tmp_path):
    s = _write(tmp_path, style_prompt="flat colors")[0]
    p, _ = apply(s, "cat, <lora:zack_IL:0.5>")
    assert p == "cat, <lora:zack_IL:0.5>, flat colors"


def test_missing_folder(tmp_path):
    assert load(str(tmp_path / "nope")) == []


# ------------------------------------------------------------------ write side
def _form(**kw):
    return {"name": "Toon", "checkpoint": "nova.safetensors", "loras": [{"name": "zack_IL.safetensors", "strength": 0.7}],
            "style_prompt": "z4ck, {prompt}", "negative": "3d", "sampler": "Euler a",
            "scheduler": "Karras", "steps": 28, "cfg": 5.5, "clip_skip": 2, **kw}


def test_validate_clamps_and_appends_marker():
    from lib_pl.kstyles import validate
    st = validate({**_form(), "steps": 9999, "cfg": 99, "clip_skip": 50, "loras": [{"name": "a.safetensors", "strength": 9}]})
    assert (st["steps"], st["cfg"], st["clip_skip"], st["loras"]) == (150, 20.0, 5, [("a", 2.0)])
    assert validate({**_form(), "style_prompt": "bold outline"})["style_prompt"] == "bold outline, {prompt}"
    import pytest
    for bad in ({}, {**_form(), "name": "  "}, {**_form(), "sampler": "Turbo"}):
        with pytest.raises(ValueError):
            validate(bad)


def test_save_update_delete_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(kstyles, "STYLES_DIR", str(tmp_path))
    monkeypatch.setattr(kstyles, "FALLBACK_DIR", None)
    fn = kstyles.save(validate(_form()))
    assert fn == "toon.json"
    doc = json.load(open(tmp_path / fn))
    assert doc["name"] == "Toon" and doc["spellbook_sampler"] == "euler_ancestral" and doc["clip_skip"] == 2
    rows = load()
    assert rows[0]["name"] == "Toon" and rows[0]["origin"] == "spellbook" and rows[0]["loras"] == [("zack_IL", 0.7)]

    # update in place; rename moves the file and reaps the old one
    assert kstyles.update("toon.json", validate({**_form(), "name": "Toon v2"})) == "toon-v2.json"
    assert sorted(os.listdir(tmp_path)) == ["toon-v2.json"]
    assert load()[0]["name"] == "Toon v2"

    # create fills a free slot when the slug is taken (name != existing style's name but slug collides)
    fn2 = kstyles.save(validate(_form(name="!Toon·v2!", checkpoint="x.safetensors")))
    assert fn2 == "toon-v2-2.json"

    # delete + errors
    kstyles.delete_file("toon-v2.json")
    assert not os.path.exists(tmp_path / "toon-v2.json")
    import pytest
    with pytest.raises(FileNotFoundError):
        kstyles.delete_file("toon-v2.json")
    with pytest.raises(ValueError):
        kstyles.delete_file("../evil.json")


def test_no_fallback_by_default(tmp_path):
    """Folder arg only. Hermetic even on machines that have a Krita styles folder installed."""
    d = {"name": "Toon", "checkpoints": ["x.safetensors"]}
    (tmp_path / "toon.json").write_text(json.dumps(d))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(kstyles, "FALLBACK_DIR", None)
        rows = load(str(tmp_path / "nope"))
    assert rows == []


def test_fallback_merges_and_shadows(tmp_path, monkeypatch):
    """Fallback styles merge in unless a same-name style belongs to the main folder; origin tags set."""
    main, fallback = tmp_path / "main", tmp_path / "fallback"
    main.mkdir(); fallback.mkdir()
    presets = str(tmp_path / "samplers.json")
    open(presets, "w").write("{}")
    for folder, name, flavor in ((main, "Shared", "main"), (fallback, "Shared", "fallback"),
                                 (fallback, "Fallback Only", "")):
        (folder / f"{name.lower().replace(' ', '-')}.json").write_text(
            json.dumps({"name": name, "checkpoints": [f"{flavor or 'x'}.safetensors"]}))
    monkeypatch.setattr(kstyles, "STYLES_DIR", str(main))
    monkeypatch.setattr(kstyles, "FALLBACK_DIR", str(fallback))
    monkeypatch.setattr(kstyles, "_presets", lambda *_: dict(kstyles.FALLBACK_PRESETS))
    rows = load(str(main), presets)
    assert [r["name"] for r in rows] == ["Fallback Only", "Shared"]
    by_name = {r["name"]: r for r in rows}
    assert by_name["Shared"]["origin"] == "spellbook" and by_name["Shared"]["checkpoint"] == "main.safetensors"
    assert by_name["Fallback Only"]["origin"] == "krita"
