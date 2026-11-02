import os

from PIL import Image, ImageDraw

from lib_pl import sheet
from lib_pl.presets import load_presets

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRESET = load_presets(os.path.join(ROOT, "presets.json"))["Toon Pin-up Action Sheet"]
CHAR = "1girl, blonde hair, glasses, green jacket"


def test_build_jobs_pose_and_face_panels():
    jobs = sheet.build_jobs(CHAR, PRESET, ["DASH", "BACK VIEW"], ["JOY"])
    assert [j["kind"] for j in jobs] == ["pose", "pose", "face"]
    dash, back, joy = jobs
    assert dash["pose"] == "dash" and back["pose"] == "pinup_back" and joy["pose"] == sheet.BUST and "fsthicc" not in joy["prompt"]
    assert "blonde hair" in dash["prompt"] and "from behind" in back["prompt"] and "laughing" in joy["prompt"]
    assert "CharacterDesign" not in dash["prompt"]  # single-figure panels never use the sheet LoRA
    assert "multiple views" in dash["negative"] and joy["size"] == sheet.FACE_SIZE


def test_payload_units_openpose_and_ipadapter():
    job = sheet.build_jobs(CHAR, PRESET, ["DEFIANT"], [])[0]
    p = sheet.payload(job, PRESET.settings, 7, 6.5, ref=Image.new("RGB", (8, 8)))
    units = p["alwayson_scripts"]["controlnet"]["args"]
    assert [u["model"] for u in units] == [sheet.IPADAPTER[1], sheet.OPENPOSE]
    assert p["seed"] == 7 and p["override_settings"]["sd_model_checkpoint"] == "novaCartoonXL_v60"
    face = sheet.payload(sheet.build_jobs(CHAR, PRESET, [], ["ANGER"])[0], PRESET.settings, 7, 6.5)
    assert [u["model"] for u in face["alwayson_scripts"]["controlnet"]["args"]] == [sheet.OPENPOSE]


def _fake(w, h):
    img = Image.new("RGB", (w, h), "white")
    ImageDraw.Draw(img).rectangle([w // 4, h // 4, w * 3 // 4, h * 3 // 4], fill="purple")
    return img


def test_run_saves_panels_and_sheet(tmp_path):
    jobs = sheet.build_jobs(CHAR, PRESET, ["DASH", "LANDING"], ["NEUTRAL", "SHOCK"])
    seen = []

    def gen(api, body):
        seen.append(body)
        return _fake(body["width"], body["height"])

    steps = list(sheet.run("http://x", jobs, PRESET.settings, 5, 6.5, str(tmp_path), gen=gen))
    assert [s[2] for s in steps] == ["DASH", "LANDING", "NEUTRAL", "SHOCK", "SHEET"]
    assert "controlnet" not in seen[0].get("alwayson_scripts", {}) or len(seen[0]["alwayson_scripts"]["controlnet"]["args"]) == 1
    assert len(seen[1]["alwayson_scripts"]["controlnet"]["args"]) == 2
    assert len(seen[2]["alwayson_scripts"]["controlnet"]["args"]) == 2  # bust: IP-Adapter + bust skeleton  # IP-Adapter ref from panel 1 + OpenPose
    out = Image.open(steps[-1][3])
    assert out.width == 2400 and (tmp_path / "sheet.json").exists() and (tmp_path / "01_dash.png").exists()


def test_weight_colors_only_hair_and_eye_colours():
    assert sheet.weight_colors("1girl, blonde hair, long hair, blue eyes, red shirt") == \
        "1girl, (blonde hair:1.2), long hair, blue eyes, red shirt"


def test_busts_drop_lower_body_tags():
    joy = sheet.build_jobs("1girl, red shirt, black shorts, sneakers, pantyhose, glasses", PRESET, [], ["JOY"])[0]
    assert "red shirt" in joy["prompt"] and "glasses" in joy["prompt"]
    assert "shorts" not in joy["prompt"] and "sneakers" not in joy["prompt"] and "pantyhose" not in joy["prompt"]
