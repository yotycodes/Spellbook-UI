import json

import pytest

from lib_pl import kstyles
from lib_pl.kstyles import apply, load


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
