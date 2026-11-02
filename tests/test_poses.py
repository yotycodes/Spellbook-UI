import json

from lib_pl.poses import detect, presets, swap


def test_detect_splits_pose_from_character():
    pose, rest = detect("1girl, red hair, standing, hand on hip, (from below:1.2), crop top, looking at viewer, <lora:x:1>")
    assert pose == ["standing", "hand on hip", "(from below:1.2)", "looking at viewer"]
    assert rest == ["1girl", "red hair", "crop top", "<lora:x:1>"]


def test_swap_replaces_only_pose():
    out = swap("1girl, red hair, standing, hand on hip, crop top", "kneeling, arched back, hands in own hair")
    assert out == "1girl, red hair, crop top, kneeling, arched back, hands in own hair"


def test_presets_from_kit(tmp_path):
    (tmp_path / "portrait").mkdir()
    (tmp_path / "portrait" / "pinup_side_adult.png").write_text("x")
    (tmp_path / "poses.json").write_text(json.dumps({
        "pinup_side": {"tags": "from side, profile, standing, speed lines", "note": "n"},
        "dash": {"tags": "running, dust cloud", "note": "d"}}))
    p = presets(str(tmp_path))
    assert p["Pin-up · side"]["tags"] == "from side, profile, standing" and p["Pin-up · side"]["skeleton"].endswith(".png")
    assert p["Action · dash"]["skeleton"] is None
    # presets() now merges the shipped 44-pose starter kit underneath
    assert any(v["key"] == "victory_arms_up" for v in p.values())
    assert len(p) >= 44


# ---- merge(): pose tags win inside the groups the pose defines; everything else stays
from lib_pl.poses import merge  # noqa: E402


def test_merge_replaces_conflicting_posture_and_view():
    out, removed, added = merge("1girl, red hair, standing, from front, upper body, holding sword, smile",
                                "lying, on stomach, from behind, full body")
    assert out == "1girl, red hair, holding sword, smile, lying, on stomach, from behind, full body"
    assert removed == ["standing", "from front", "upper body"]
    assert added == ["lying", "on stomach", "from behind", "full body"]


def test_merge_keeps_groups_the_pose_does_not_define():
    out, removed, _ = merge("1girl, sitting, looking at viewer, crossed arms", "standing")
    assert out == "1girl, looking at viewer, crossed arms, standing"
    assert removed == ["sitting"]


def test_merge_keeps_more_specific_compatible_tag():
    out, removed, added = merge("1girl, (lying on back:1.2), smile", "lying, full body")
    assert out == "1girl, (lying on back:1.2), smile, full body"
    assert removed == [] and added == ["full body"]


def test_merge_drops_standing_only_tags_when_not_standing():
    out, removed, _ = merge("1girl, contrapposto, wide stance, hip pop", "kneeling")
    assert out == "1girl, kneeling"
    assert removed == ["contrapposto", "wide stance", "hip pop"]


def test_merge_dedupes_and_never_touches_loras_or_props():
    out, removed, added = merge("<lora:x:0.7>, 1girl, standing, standing, holding phone", "standing, arms up")
    assert out == "<lora:x:0.7>, 1girl, standing, holding phone, arms up"
    assert removed == [] and added == ["arms up"]


def test_merge_underscores_and_case():
    out, removed, _ = merge("1girl, From_Behind, Full_Body", "from side, cowboy shot")
    assert out == "1girl, from side, cowboy shot"
    assert removed == ["From_Behind", "Full_Body"]


def test_merge_specific_prompt_tag_must_agree_with_whole_pose_group():
    out, removed, added = merge("1girl, lying on back, lying", "lying, on stomach")
    assert out == "1girl, lying, on stomach"
    assert removed == ["lying on back"] and added == ["on stomach"]


# ---- resolve(): conflicting tags inside one prompt, first written wins
from lib_pl.poses import resolve  # noqa: E402


def test_resolve_posture_view_height_conflicts_first_wins():
    out, removed = resolve("1girl, standing, from front, from above, sitting, from behind, from below, smile")
    assert out == "1girl, standing, from front, from above, smile"
    assert removed == ["sitting", "from behind", "from below"]


def test_resolve_keeps_compatible_pairs():
    for p in ("1girl, lying, on back, reclining", "1girl, standing, bent over, leaning forward",
              "1girl, kneeling, on knees", "1girl, from side, profile", "1girl, looking back, looking at viewer"):
        assert resolve(p) == (p, [])


def test_resolve_lying_directions_conflict():
    out, removed = resolve("1girl, lying on back, on stomach")
    assert out == "1girl, lying on back" and removed == ["on stomach"]


def test_resolve_leaves_loras_and_segments():
    p = "<lora:a:1>, standing BREAK sitting, 1boy"
    assert resolve(p) == (p, [])


def test_facing_filter_back_drops_front_words():
    from lib_pl.poses import facing_filter
    p = "1girl, large breasts, cleavage, navel, open mouth, pink hair, <lora:x:0.8>, looking at viewer"
    out, gone = facing_filter(p, "back", face_visible=True)
    assert out == "1girl, open mouth, pink hair, <lora:x:0.8>, looking at viewer"
    assert gone == ["large breasts", "cleavage", "navel"]


def test_facing_filter_back_without_face_drops_face_words():
    from lib_pl.poses import facing_filter
    out, gone = facing_filter("1girl, adult face, open mouth, smile, pink hair, boobs", "back", face_visible=False)
    assert out == "1girl, pink hair" and "open mouth" in gone and "boobs" in gone


def test_facing_filter_front_drops_back_words():
    from lib_pl.poses import facing_filter
    p = "1girl, looking back, view from behind touching hair, (from behind:1.2), bare back, ass, pink hair"
    out, gone = facing_filter(p, "front")
    assert out == "1girl, ass, pink hair"
    assert len(gone) == 4


def test_facing_filter_side_or_unknown_changes_nothing():
    from lib_pl.poses import facing_filter
    assert facing_filter("1girl, breasts, from behind", None) == ("1girl, breasts, from behind", [])
    assert facing_filter("1girl, breasts", "side") == ("1girl, breasts", [])


def test_pose_facing_from_tags():
    from lib_pl.poses import pose_facing
    assert pose_facing(["from behind", "looking back"]) == ("back", True)
    assert pose_facing("from behind, full body") == ("back", False)
    assert pose_facing(["front view", "standing"]) == ("front", True)
    assert pose_facing(["from side"]) == (None, True)


def test_facing_filter_keeps_postures():
    from lib_pl.poses import facing_filter
    out, gone = facing_filter("1girl, lying on stomach, on belly, stomach", "back")
    assert out == "1girl, lying on stomach, on belly" and gone == ["stomach"]


def test_pose_wins_removes_conflicts_without_adding():
    from lib_pl.poses import pose_wins
    p = "1girl, standing, arm under breasts, eye-level shot, smile, <lora:x:0.5>"
    out, gone = pose_wins(p, "lying, arms up, from below")
    assert out == "1girl, smile, <lora:x:0.5>"
    assert set(gone) == {"standing", "arm under breasts", "eye-level shot"}
    assert pose_wins("1girl, lying", "lying") == ("1girl, lying", [])
    assert pose_wins("1girl, standing", "") == ("1girl, standing", [])


def test_new_conflict_tags_are_known():
    from lib_pl.poses import merge
    out, removed, _ = merge("1girl, wading, arm at side, legs together", "kneeling, hand on own head, legs apart")
    assert set(removed) == {"wading", "arm at side", "legs together"}


def test_facing_filter_cleans_inside_groups_keeping_the_rest():
    from lib_pl.poses import facing_filter
    assert facing_filter("((1girl, dva, cleavage)), pink hair", "back")[0] == "((1girl, dva)), pink hair"
    assert facing_filter("((1girl, dva, cleavage:1.3)), pink hair", "back")[0] == "((1girl, dva:1.3)), pink hair"
    assert facing_filter("((cleavage, navel)), pink hair", "back")[0] == "pink hair"
    assert facing_filter("((navel:1.2)), pink hair", "back")[0] == "pink hair"


def test_weighted_pose_tags_can_conflict():
    from lib_pl.poses import pose_wins
    out, gone = pose_wins("((sitting on bench:1.4)), ((crossed legs:1.4)), pink hair", "standing, legs apart")
    assert out == "pink hair" and len(gone) == 2
    assert pose_wins("((sitting:1.4)), pink hair", "sitting, crossed legs")[0] == "((sitting:1.4)), pink hair"


def test_more_specific_pose_wording_keeps_your_emphasis():
    from lib_pl.poses import merge, pose_wins
    out, removed, added = merge("1girl, ((lying:1.4)), pink hair", "lying on back, full body")
    assert out == "1girl, ((lying on back:1.4)), pink hair, full body"
    assert pose_wins("1girl, ((lying:1.4))", "lying on back")[0] == "1girl, ((lying on back:1.4))"


def test_pose_words_inside_groups_are_checked():
    from lib_pl.poses import pose_wins
    out, gone = pose_wins("((mikasa, sitting, crossed legs:1.3)), black hair, ((standing:1.2))", "standing, legs apart, arms up")
    assert out == "((mikasa:1.3)), black hair, ((standing:1.2))" and gone == ["sitting", "crossed legs"]
    assert pose_wins("((sitting, crossed legs)), black hair", "standing, legs apart")[0] == "black hair"
    assert pose_wins("((sitting, crossed legs)), black hair", "standing")[0] == "((crossed legs)), black hair"   # legs left open by the pose
    assert pose_wins("((mikasa, black hair)), smile", "standing") == ("((mikasa, black hair)), smile", [])


def test_resting_arms_fight_a_pose_that_sets_the_arms():
    from lib_pl.poses import pose_wins
    out, gone = pose_wins("((arms resting on the bench:1.4)), hands in lap, black hair", "standing, arms up")
    assert out == "black hair" and len(gone) == 2


def test_closeup_spellings_fight_a_full_body_pose():
    from lib_pl.poses import merge
    for word in ("closeup", "close up", "close-up", "extreme closeup"):
        out, gone, _ = merge(f"1girl, {word}, smile", "full body, standing")
        assert word in gone and "full body" in out, word


def test_camera_angle_and_torso_shape_always_follow_the_skeleton():
    from lib_pl.poses import merge, pose_wins
    out, gone, _ = merge("1girl, from below, dynamic angle, dutch angle, (arched back:1.6), red dress", "sitting")
    assert set(gone) == {"from below", "dynamic angle", "dutch angle", "(arched back:1.6)"}
    assert "red dress" in out
    assert merge("1girl, from below", "")[1] == []                      # no pose: nothing removed
    assert pose_wins("1girl, ((arched back, red hair:1.2))", "standing")[0] == "1girl, ((red hair:1.2))"


def test_back_view_drops_genital_words_unless_the_pose_shows_them():
    from lib_pl.poses import facing_filter
    p = "1girl, ass focus, pussy, wet spot, grool, red hair"
    out, gone = facing_filter(p, "back", True, pose_tags=["from behind", "standing"])
    assert set(gone) == {"pussy", "wet spot", "grool"} and "ass focus" in out
    for posture in ("bent over", "all fours", "kneeling", "leg up"):
        assert facing_filter(p, "back", True, pose_tags=["from behind", posture])[1] == [], posture
    assert facing_filter(p, "back", True)[1] == []      # callers that don't pass the pose's tags: unchanged
