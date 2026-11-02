import json

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
