import os
from lib_pl.presets import Preset, load_presets, merge_csv, to_infotext

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_load_presets_reads_all_entries():
    import json
    path = os.path.join(ROOT, "presets.json")
    presets = load_presets(path)
    assert list(presets)[:3] == ["WAI-illustrious", "Reedy (Illustrious)", "Nova Toon"]
    wai = presets["WAI-illustrious"]
    assert isinstance(wai, Preset)
    assert wai.style == "tags"
    assert wai.settings["steps"] == 30
    # reads every entry present in the file, whatever the count
    with open(path) as f:
        assert set(presets) == {p["name"] for p in json.load(f)}
    assert presets["Toon Pin-up Sheet"].subject_only and presets["Toon Pin-up Dynamic"].subject_only
    assert presets["Flux"].style == "natural"


def test_merge_csv_dedupes_case_insensitive_keeps_order():
    assert merge_csv("masterpiece, best quality", "Best Quality, 1girl, solo, 1girl") == "masterpiece, best quality, 1girl, solo"


def test_merge_csv_handles_empty_parts():
    assert merge_csv("", "1girl, ") == "1girl"
    assert merge_csv("a", "") == "a"


def test_to_infotext_sdxl():
    s = {"sampler": "Euler a", "scheduler": "Automatic", "steps": 30, "cfg": 7, "clip_skip": 2, "width": 832, "height": 1216}
    text = to_infotext("1girl, solo", "bad hands", s)
    assert text == (
        "1girl, solo\n"
        "Negative prompt: bad hands\n"
        "Steps: 30, Sampler: Euler a, Schedule type: Automatic, CFG scale: 7, Size: 832x1216, Clip skip: 2"
    )


def test_to_infotext_flux_no_negative_has_distilled():
    s = {"sampler": "Euler", "scheduler": "Simple", "steps": 25, "cfg": 1, "distilled_cfg": 3.5, "width": 768, "height": 1344}
    text = to_infotext("A woman.", "", s)
    assert text == (
        "A woman.\n"
        "Steps: 25, Sampler: Euler, Schedule type: Simple, CFG scale: 1, Distilled CFG Scale: 3.5, Size: 768x1344"
    )


def test_to_infotext_flattens_newlines():
    s = {"sampler": "Euler a", "scheduler": "Automatic", "steps": 30, "cfg": 7, "clip_skip": 2, "width": 832, "height": 1216}
    text = to_infotext("1girl,\nsmile\nNegative prompt: x", "bad\nhands", s)
    lines = text.split("\n")
    assert len(lines) == 3
    assert lines[0] == "1girl, smile Negative prompt: x"
    assert lines[1] == "Negative prompt: bad hands"


def test_nova_toon_prefix_escapes_parens():
    presets = load_presets(os.path.join(os.path.dirname(os.path.dirname(__file__)), "presets.json"))
    assert "toon \\(style\\)" in presets["Nova Toon"].quality_prefix


def test_banned_tags_loaded_per_preset():
    presets = load_presets(os.path.join(ROOT, "presets.json"))
    for name in ("WAI-illustrious", "Reedy (Illustrious)", "Nova Toon"):
        banned = [b.lower() for b in presets[name].banned_tags]
        for junk in ("realistic", "3d", "photo", "anime", "danbooru"):
            assert junk in banned, (name, junk)
    assert "photo" not in [b.lower() for b in presets["Pony Realism"].banned_tags]
    assert list(presets["Flux"].banned_tags) == []
