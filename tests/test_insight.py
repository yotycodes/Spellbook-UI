from lib_pl.insight import group_of, group_tags, lora_suggestions, similar


def test_group_of():
    assert group_of("blue eyes") == "Appearance"
    assert group_of("hand on hip") == "Pose & framing"
    assert group_of("simple background") == "Background"
    assert group_of("outdoors") == "Background"
    assert group_of("open mouth") == "Expression"
    assert group_of("smile") == "Expression"
    assert group_of("star hair ornament") == "Appearance"
    assert group_of("anime coloring") == "Other"


def test_group_tags_puts_named_first():
    out = group_tags({"character": [("haruno sakura", 0.95)], "general": [("pink hair", 0.9), ("standing", 0.6)]})
    assert [(x["tag"], x["group"]) for x in out] == [
        ("haruno sakura", "Character"), ("pink hair", "Appearance"), ("standing", "Pose & framing")]


def test_similar_ranks_by_weighted_overlap():
    rows = [
        {"id": 1, "prompt": "1girl, pink hair, green eyes", "nsfw": "None", "react": 5},
        {"id": 2, "prompt": "haruno_sakura, pink hair", "nsfw": "None", "react": 1},
        {"id": 3, "prompt": "haruno sakura, pink hair", "nsfw": "X", "react": 99},
        {"id": 4, "prompt": "landscape", "nsfw": "None", "react": 50},
    ]
    tags = [("haruno sakura", 0.9, True), ("pink hair", 0.8, False), ("green eyes", 0.5, False), ("1girl", 0.99, False)]
    out = similar(rows, tags, safe_values=("None",))
    assert [r["id"] for r in out] == [2, 1]


def test_lora_suggestions(tmp_path):
    for f in ("sakura_haruno_v2.safetensors", "pinkHairStyle.safetensors", "other.safetensors", "notes.txt"):
        (tmp_path / f).write_text("x")
    assert lora_suggestions(["haruno sakura", "solo"], str(tmp_path)) == ["sakura_haruno_v2"]
    assert lora_suggestions(["pink hair"], str(tmp_path)) == ["pinkHairStyle"]
    assert lora_suggestions(["x"], str(tmp_path / "missing")) == []
