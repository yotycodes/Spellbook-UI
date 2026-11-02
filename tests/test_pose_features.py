import numpy as np
from PIL import Image, ImageDraw

from lib_pl.pose_features import HUES, LIMBS, analyze, prompt_tags, similar, vector


def _draw(tmp_path, pts, name="p.png"):
    """Render a COCO-18 skeleton the way OpenPose does: each limb in its own hue."""
    import colorsys
    im = Image.new("RGB", (512, 768), (0, 0, 0))
    d = ImageDraw.Draw(im)
    for i, (a, b) in enumerate(LIMBS):
        if pts[a] is None or pts[b] is None:
            continue
        r, g, bl = colorsys.hsv_to_rgb(HUES[i] / 360, 1, 0.6)
        d.line([tuple(pts[a]), tuple(pts[b])], fill=(int(r * 255), int(g * 255), int(bl * 255)), width=8)
    p = tmp_path / name
    im.save(p)
    return str(p)


STAND = [(256, 120), (256, 160), (216, 160), (206, 240), (200, 320), (296, 160), (306, 240), (312, 320),
         (230, 330), (228, 470), (226, 610), (282, 330), (284, 470), (286, 610), (246, 110), (266, 110), (236, 116), (276, 116)]


def test_standing_front_full_body(tmp_path):
    r = analyze(_draw(tmp_path, STAND))
    assert {"standing", "front view", "full body"} <= set(r["tags"])
    assert "sitting" not in r["tags"] and "group" not in r["tags"]


def test_arms_up(tmp_path):
    pts = list(STAND)
    pts[3], pts[4] = (206, 110), (200, 40)
    pts[6], pts[7] = (306, 110), (312, 40)
    assert "arms up" in analyze(_draw(tmp_path, pts))["tags"]


def test_similar_ranks_itself_first(tmp_path):
    a = analyze(_draw(tmp_path, STAND, "a.png"))["v"]
    pts = list(STAND)
    pts[3], pts[4] = (206, 110), (200, 40)
    b = analyze(_draw(tmp_path, pts, "b.png"))["v"]
    ranked = similar(a, [("b", b), ("a", a)])
    assert ranked[0][0] == "a"


def test_prompt_tags():
    assert prompt_tags(["standing", "front view", "hands on hips"]) == "standing, hands on own hips"


def test_match_scores_same_pose_100_and_different_pose_low(tmp_path):
    from lib_pl.pose_features import match
    a = analyze(_draw(tmp_path, STAND, "a.png"))["v"]
    assert match(a, a) == 100
    up = list(STAND)
    up[3], up[4] = (206, 110), (200, 40)
    up[6], up[7] = (306, 110), (312, 40)
    sit = list(up)
    sit[9], sit[10], sit[12], sit[13] = (150, 330), (150, 440), (360, 330), (360, 440)
    b = analyze(_draw(tmp_path, sit, "b.png"))["v"]
    assert match(a, b) <= 60


def _figure():
    """A standing figure in vector() space: every limb has a direction."""
    v = [[0.0, 0.0]] * 18
    v[2], v[3], v[4] = [-0.3, 0.0], [-0.4, 0.5], [-0.45, 1.0]
    v[5], v[6], v[7] = [0.3, 0.0], [0.4, 0.5], [0.45, 1.0]
    v[8], v[9], v[10] = [-0.15, 1.0], [-0.2, 2.0], [-0.2, 3.0]
    v[11], v[12], v[13] = [0.15, 1.0], [0.2, 2.0], [0.2, 3.0]
    return v


def test_match_missing_result_joint_is_a_miss():
    from lib_pl.pose_features import match
    t = _figure()
    r = list(t)
    r[4] = None   # right wrist not found in the result
    assert match(t, r) == round(100 * 11 / 12)
    assert match(t, None) is None
    assert match([None] * 18, r) is None


def test_match_ignores_which_side_is_called_right():
    from lib_pl.pose_features import SWAP, match
    t = [[float(i), float(i % 3)] for i in range(18)]
    mirrored_labels = [t[j] for j in SWAP]
    assert match(t, mirrored_labels) == 100


def test_facing_from_shoulder_order():
    from lib_pl.pose_features import facing
    v = [None] * 18
    v[2], v[5] = [-0.3, 0], [0.3, 0]     # right shoulder on image left
    assert facing(v) == "front"
    v[2], v[5] = [0.3, 0], [-0.3, 0]
    assert facing(v) == "back"
    v[2], v[5] = [0.05, 0], [-0.02, 0]   # side view: too close to tell
    assert facing(v) is None


def test_expected_facing():
    from lib_pl.pose_features import expected_facing
    assert expected_facing(["from behind", "standing"]) == "back"
    assert expected_facing(["front view"]) == "front"
    assert expected_facing(["from side"]) is None
    assert expected_facing([]) is None


def test_back_shoulders_with_face_is_looking_back(tmp_path):
    pts = list(STAND)
    for a, b in ((2, 5), (3, 6), (4, 7), (8, 11), (9, 12), (10, 13)):   # swap sides: right limbs on image right
        pts[a], pts[b] = pts[b], pts[a]
    tags = analyze(_draw(tmp_path, pts))["tags"]
    assert {"from behind", "looking back"} <= set(tags) and "front view" not in tags


def test_headless_skeleton_is_not_a_back_view(tmp_path):
    pts = list(STAND)
    for i in (0, 14, 15, 16, 17):
        pts[i] = None
    tags = analyze(_draw(tmp_path, pts))["tags"]
    assert "from behind" not in tags


def test_ear_dots_without_face_is_a_back_view(tmp_path):
    from PIL import ImageDraw
    pts = list(STAND)
    for i in (0, 14, 15, 16, 17):
        pts[i] = None
    path = _draw(tmp_path, pts)
    im = Image.open(path)
    d = ImageDraw.Draw(im)
    for (x, y), rgb in (((236, 116), (255, 0, 170)), ((276, 116), (255, 0, 85))):   # ear keypoint dots
        d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=rgb)
    im.save(path)
    assert "from behind" in analyze(path)["tags"]


def test_readability_tiers():
    from lib_pl.pose_features import readability
    full = [[0.0, 0.0]] * 18
    assert readability(full, ["front view"]) == ("clear", "")
    assert readability(full, ["full body"])[0] == "partial"
    few = [None] * 18
    few[2] = few[5] = few[8] = [0.0, 0.0]
    assert readability(few, ["front view"])[0] == "unclear"
    assert readability(None, [])[0] == "unclear"
    assert readability(full, ["front view"], nonstandard=True) == ("unclear", "drawn in a non-standard style")


def test_match_ignores_body_proportions():
    """Same pose drawn with a long torso and short legs (curvy / toon styles) still matches fully."""
    from lib_pl.pose_features import match
    t = _figure()
    r = [list(p) for p in t]
    for i in (8, 9, 10, 11, 12, 13):
        r[i][1] = t[i][1] * 0.75 + 0.3   # hips lower, legs shorter
    assert match(t, r) == 100


def test_match_arms_and_legs_swap_sides_separately():
    from lib_pl.pose_features import match
    t = _figure()
    t[3], t[4] = [-0.8, -0.2], [-1.2, -0.5]   # right arm raised
    t[9], t[10] = [-0.6, 1.8], [-0.9, 2.6]    # right leg out
    r = list(t)
    r[2], r[3], r[4], r[5], r[6], r[7] = t[5], t[6], t[7], t[2], t[3], t[4]   # arm labels swapped, legs not
    assert match(t, r) == 100
