"""Shipped 50-pose starter kit: tracked standalone/pose-starter/ +
merged presets() = SHIP_KIT overlaid by the user kit (env > spellbook.json > .pose-kit)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "standalone"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHIP_KIT = os.path.join(HERE, "standalone", "pose-starter")


def test_shipped_kit_contents():
    poses = json.load(open(os.path.join(SHIP_KIT, "poses.json"), encoding="utf-8"))
    p29 = json.load(open(os.path.join(SHIP_KIT, "poses-29.json"), encoding="utf-8"))
    p15 = json.load(open(os.path.join(SHIP_KIT, "poses-15.json"), encoding="utf-8"))
    assert len(poses) == 44, f"shipped kit must be exactly 44 poses, got {len(poses)}"
    assert len(p29) == 29 and len(p15) == 15 and not (set(p29) & set(p15))
    assert poses == {**p29, **p15}
    # user decision 2026-11-01: the boudoir layer does not ship
    assert not any("boudoir" in k for k in poses)
    assert not os.path.isdir(os.path.join(SHIP_KIT, "boudoir"))
    for name, rec in poses.items():
        assert rec.get("tags"), f"{name} has no tags"
        assert isinstance(rec.get("note", ""), str)


def test_shipped_skeletons_resolve():
    poses = json.load(open(os.path.join(SHIP_KIT, "poses.json"), encoding="utf-8"))
    missing = []
    for name in poses:
        found = False
        for sub, suffix in (("portrait", "_adult"), ("boudoir", "_adult"), ("chibi", "_chibi")):
            if os.path.exists(os.path.join(SHIP_KIT, sub, f"{name}{suffix}.png")):
                found = True
                break
        if not found:
            missing.append(name)
    assert not missing, f"shipped poses without skeleton files: {missing}"


def test_authored_skeletons_are_openpose_style():
    """The 15 hand-authored skeletons: dark canvas + colored limb pixels + cyan joints."""
    from PIL import Image
    names = json.load(open(os.path.join(SHIP_KIT, "poses-15.json"), encoding="utf-8"))
    assert len(names) == 15
    for name in names:
        path = os.path.join(SHIP_KIT, "portrait", f"{name}_adult.png")
        assert os.path.exists(path), name
        px = Image.open(path).convert("RGB")
        colors = {p for p in px.getdata() if p != (0, 0, 0)}
        satur = [c for c in colors if max(c) > 120 and max(c) - min(c) > 60]
        assert any(any(d > 200 for d in c if c != (0, 255, 255)) for c in satur), \
            f"{name}: no saturated limb colors (not OpenPose-format)"


def test_merged_presets_fresh_machine(monkeypatch):
    """No .pose-kit, no env config: the shipped kit alone yields 50 usable presets."""
    import lib_pl.poses as poses_mod
    monkeypatch.setenv("SPELLBOOK_POSE_KIT", "/nonexistent/pose-kit")
    import importlib
    importlib.reload(poses_mod)
    try:
        p = poses_mod.presets()
        assert len(p) == 44
        assert not [k for k, v in p.items() if not v["skeleton"]]
        assert all(v["tags"] for v in p.values())
        # user kit wins on key conflicts: overlay above ship kit
        assert p["Action · victory arms up"]["key"] == "victory_arms_up"
    finally:
        importlib.reload(poses_mod)

def test_user_kit_overrides_ship_kit(tmp_path, monkeypatch):
    import lib_pl.poses as poses_mod
    (tmp_path / "portrait").mkdir()
    (tmp_path / "portrait" / "victory_arms_up_adult.png").write_text("x")
    (tmp_path / "poses.json").write_text(json.dumps({
        "victory_arms_up": {"tags": "custom victory tags", "note": "mine"}}))
    monkeypatch.setenv("SPELLBOOK_POSE_KIT", str(tmp_path))
    import importlib
    importlib.reload(poses_mod)
    try:
        p = poses_mod.presets()
        assert p["Action · victory arms up"]["tags"] == "custom victory tags"
        assert p["Action · victory arms up"]["skeleton"].startswith(str(tmp_path))
    finally:
        importlib.reload(poses_mod)


def test_spellbook_json_kit_dir(tmp_path, monkeypatch):
    """Config chain: spellbook.json pose_kit_dir is honored when the env var is unset."""
    import lib_pl.poses as poses_mod
    (tmp_path / "poses.json").write_text(json.dumps({"custom_only": {"tags": "alone"}}))
    with open(os.path.join(str(tmp_path), "spellbook.json"), "w") as f:
        json.dump({"pose_kit_dir": str(tmp_path)}, f)
    monkeypatch.delenv("SPELLBOOK_POSE_KIT", raising=False)
    monkeypatch.setattr(poses_mod, "_BETA_ROOT", str(tmp_path))
    assert poses_mod._user_kit_dir() == str(tmp_path)
    p = poses_mod.presets(poses_mod._user_kit_dir())
    assert "Action · custom only" in p and p["Action · custom only"]["tags"] == "alone"
