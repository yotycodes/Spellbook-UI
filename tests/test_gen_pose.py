import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "standalone"))
import gen  # noqa: E402


def test_pose_mode_auto_follows_lora_count():
    assert gen._pose_mode({}, "a girl") == "Balanced"
    assert gen._pose_mode({}, "a girl <lora:a:0.7> <lora:b:0.5>") == "ControlNet is more important"
    assert gen._pose_mode({"pose_mode": "auto"}, "<lora:a:1>") == "Balanced"


def test_pose_mode_explicit_choice_wins():
    assert gen._pose_mode({"pose_mode": "pose"}, "") == "ControlNet is more important"
    assert gen._pose_mode({"pose_mode": "prompt"}, "<lora:a:1> <lora:b:1>") == "My prompt is more important"
    assert gen._pose_mode({"pose_mode": "balanced"}, "<lora:a:1> <lora:b:1>") == "Balanced"
    assert gen._pose_mode({"pose_mode": "nonsense"}, "") == "Balanced"


def test_pose_unit_fills_instead_of_cropping(tmp_path, monkeypatch):
    skel = tmp_path / "s.png"
    skel.write_bytes(b"png")
    monkeypatch.setattr(gen, "_cn_model", lambda prefix: "xinsir_openpose_sdxl [abc]")
    out = {"prompt": "x"}
    gen._extras(out, {"pose_skeleton": str(skel)})
    unit = out["alwayson_scripts"]["ControlNet"]["args"][0]
    assert unit["resize_mode"] == "Resize and Fill"
    assert unit["control_mode"] == "Balanced"


def test_missing_skeleton_means_no_pose_unit(tmp_path):
    out = {"prompt": "x"}
    gen._extras(out, {"pose_skeleton": str(tmp_path / "gone.png")})
    assert "alwayson_scripts" not in out


def test_retry_until_pose_matches(tmp_path, monkeypatch):
    monkeypatch.setitem(gen.CFG, "out_dir", str(tmp_path))
    skel = tmp_path / "s.png"
    skel.write_bytes(b"png")
    scores = iter([40, 55, 90])
    monkeypatch.setitem(gen.CFG, "pose_score", lambda s, img, p: next(scores))
    n = {"i": 0}

    def fake_generate(job, params, attempt=1):
        n["i"] += 1
        name = f"img{n['i']}.png"
        return [{"name": name, "seed": params.get("seed"), "attempt": attempt}]
    monkeypatch.setattr(gen, "_generate", fake_generate)
    job = {"status": "running", "total": 1,
           "params": {"pose_skeleton": str(skel), "pose_min": 70, "pose_retries": 3, "seed": 5}}
    saved = gen._run_job(job)
    assert [m["pose_score"] for m in saved] == [40, 55, 90]
    assert saved[1]["seed"] == -1 and job["total"] == 3


def test_no_retry_when_off(tmp_path, monkeypatch):
    monkeypatch.setitem(gen.CFG, "out_dir", str(tmp_path))
    skel = tmp_path / "s.png"
    skel.write_bytes(b"png")
    monkeypatch.setitem(gen.CFG, "pose_score", lambda s, img, p: 10)
    monkeypatch.setattr(gen, "_generate", lambda job, params, attempt=1: [{"name": "a.png"}])
    saved = gen._run_job({"status": "running", "total": 1, "params": {"pose_skeleton": str(skel)}})
    assert len(saved) == 1 and saved[0]["pose_score"] == 10


def test_back_pose_adds_from_behind(monkeypatch):
    monkeypatch.setitem(gen.CFG, "pose_view", lambda p, s: ["from behind", "looking back", "standing"])
    out = {"prompt": "1girl, hoodie"}
    gen._back_view_tags(out, {}, "s.png")
    assert out["prompt"] == "1girl, hoodie, (from behind:1.2), looking back"


def test_back_pose_keeps_prompt_that_already_says_it(monkeypatch):
    monkeypatch.setitem(gen.CFG, "pose_view", lambda p, s: ["from behind"])
    out = {"prompt": "1girl, back view"}
    gen._back_view_tags(out, {}, "s.png")
    assert out["prompt"] == "1girl, back view"


def test_front_pose_prompt_untouched(monkeypatch):
    monkeypatch.setitem(gen.CFG, "pose_view", lambda p, s: ["front view"])
    out = {"prompt": "1girl"}
    gen._back_view_tags(out, {}, "s.png")
    assert out["prompt"] == "1girl"


def test_score_dict_stores_facing(tmp_path, monkeypatch):
    monkeypatch.setitem(gen.CFG, "out_dir", str(tmp_path))
    monkeypatch.setitem(gen.CFG, "pose_score", lambda s, img, p: {"score": 30, "facing": "wrong: front instead of back"})
    saved = [{"name": "a.png"}]
    gen._score_pose(saved, "s.png", {})
    assert saved[0]["pose_score"] == 30 and saved[0]["pose_facing"].startswith("wrong")


def test_depth_unit_added_when_pose_has_depth(tmp_path, monkeypatch):
    skel, depth = tmp_path / "s.png", tmp_path / "s_depth.png"
    skel.write_bytes(b"png"); depth.write_bytes(b"png")
    monkeypatch.setitem(gen.CFG, "pose_pack_path", lambda pid: str(skel))
    monkeypatch.setitem(gen.CFG, "pose_depth_path", lambda pid: str(depth))
    monkeypatch.setitem(gen.CFG, "pose_view", lambda p, s: [])
    monkeypatch.setattr(gen, "_cn_model", lambda prefix: prefix + " [x]")
    out = {"prompt": "x"}
    gen._extras(out, {"pose_pack_id": "abc", "pose_depth": True})
    units = out["alwayson_scripts"]["ControlNet"]["args"]
    assert len(units) == 2 and units[1]["model"].startswith("xinsir_depth") and units[1]["weight"] == 0.45
    out = {"prompt": "x"}
    gen._extras(out, {"pose_pack_id": "abc", "pose_depth": False})
    assert len(out["alwayson_scripts"]["ControlNet"]["args"]) == 1


def test_wrong_facing_triggers_retry(tmp_path, monkeypatch):
    monkeypatch.setitem(gen.CFG, "out_dir", str(tmp_path))
    skel = tmp_path / "s.png"
    skel.write_bytes(b"png")
    res = iter([{"score": 30, "facing": "wrong: front instead of back"}, {"score": 90, "facing": "ok"}])
    monkeypatch.setitem(gen.CFG, "pose_score", lambda s, img, p: next(res))
    n = {"i": 0}

    def fake_generate(job, params, attempt=1):
        n["i"] += 1
        return [{"name": f"i{n['i']}.png"}]
    monkeypatch.setattr(gen, "_generate", fake_generate)
    saved = gen._run_job({"status": "running", "total": 1, "params": {"pose_skeleton": str(skel), "pose_min": 60}})
    assert [m["pose_facing"] for m in saved] == ["wrong: front instead of back", "ok"]


def test_unjudgeable_score_does_not_retry(tmp_path, monkeypatch):
    monkeypatch.setitem(gen.CFG, "out_dir", str(tmp_path))
    skel = tmp_path / "s.png"
    skel.write_bytes(b"png")
    monkeypatch.setitem(gen.CFG, "pose_score", lambda s, img, p: {"score": None, "facing": None})
    monkeypatch.setattr(gen, "_generate", lambda job, params, attempt=1: [{"name": "a.png"}])
    saved = gen._run_job({"status": "running", "total": 1, "params": {"pose_skeleton": str(skel), "pose_min": 75}})
    assert len(saved) == 1


def test_generate_filters_words_facing_the_other_way(monkeypatch):
    monkeypatch.setitem(gen.CFG, "pose_view", lambda p, s: ["from behind", "full body"])
    out = {"prompt": "1girl, boobs, adult face, open mouth, pink hair"}
    gen._back_view_tags(out, {}, "s.png")
    assert out["prompt"] == "1girl, pink hair, (from behind:1.2)"
    out = {"prompt": "1girl, boobs, pink hair"}
    gen._back_view_tags(out, {"pose_facing_filter": False}, "s.png")
    assert out["prompt"] == "1girl, boobs, pink hair, (from behind:1.2)"


def test_generate_front_pose_drops_back_words(monkeypatch):
    monkeypatch.setitem(gen.CFG, "pose_view", lambda p, s: ["front view", "standing"])
    out = {"prompt": "1girl, looking back, from behind, pink hair"}
    gen._back_view_tags(out, {}, "s.png")
    assert out["prompt"] == "1girl, pink hair"


def test_generate_drops_prompt_tags_that_fight_the_pose(monkeypatch):
    monkeypatch.setitem(gen.CFG, "pose_view", lambda p, s: ["front view", "lying", "arms up"])
    out = {"prompt": "1girl, standing, arm under breasts, pink hair"}
    gen._back_view_tags(out, {}, "s.png")
    assert out["prompt"] == "1girl, pink hair"


def test_fix_body_runs_before_face_and_hands(monkeypatch):
    out = {"prompt": "x"}
    gen._extras(out, {"fix_body": True, "fix_face": True, "fix_hands": True})
    units = out["alwayson_scripts"]["ADetailer"]["args"][2:]
    assert [u["ad_model"] for u in units] == ["person_yolov8s-seg.pt", "face_yolov8n.pt", "hand_yolov8n.pt"]
    assert units[0]["ad_denoising_strength"] == 0.35


def test_unchecked_results_do_not_trigger_retry():
    assert gen._pose_ok({"pose_score": None, "pose_facing": "unchecked: no body found by the pose reader"}, 75)
    assert not gen._pose_ok({"pose_score": 30, "pose_facing": "wrong: front instead of back"}, 0)


def test_fix_only_job_skips_img2img():
    out = {"prompt": "x"}
    gen._extras(out, {"fix_face": True, "ad_only": True})
    assert out["alwayson_scripts"]["ADetailer"]["args"][:2] == [True, True]
    out = {"prompt": "x"}
    gen._extras(out, {"fix_face": True})
    assert out["alwayson_scripts"]["ADetailer"]["args"][:2] == [True, False]


def test_picked_pose_wins_whatever_the_priority(monkeypatch):
    monkeypatch.setitem(gen.CFG, "pose_view", lambda p, s: ["front view", "standing"])
    for mode in ("prompt", "pose", "auto"):
        out = {"prompt": "1girl, ((sitting:1.4)), pink hair"}
        gen._back_view_tags(out, {"pose_mode": mode}, "s.png")
        assert out["prompt"] == "1girl, pink hair"


def _reset_queue(monkeypatch, tmp_path):
    monkeypatch.setattr(gen, "_queue", [])
    monkeypatch.setitem(gen.CFG, "queue_file", str(tmp_path / "queue.json"))
    monkeypatch.setattr(gen, "_start_worker", lambda: None)


def test_queue_is_saved_and_comes_back_paused(tmp_path, monkeypatch):
    _reset_queue(monkeypatch, tmp_path)
    gen.run(params=None, jobs=[{"params": {"prompt": "a", "count": 2}, "label": "a"}, {"params": {"prompt": "b"}, "label": "b"}])
    assert gen.unfinished() == (2, 3)
    monkeypatch.setattr(gen, "_queue", [])            # app restarts
    assert gen.restore_queue(str(tmp_path / "queue.json")) == 2
    assert [j["status"] for j in gen._queue] == ["held", "held"]
    assert gen.resume()["resumed"] == 2
    assert [j["status"] for j in gen._queue] == ["queued", "queued"]


def test_dont_save_forgets_the_queue(tmp_path, monkeypatch):
    _reset_queue(monkeypatch, tmp_path)
    monkeypatch.setattr(gen, "_call", lambda *a, **k: {})
    gen.run(params=None, jobs=[{"params": {"prompt": "a"}, "label": "a"}])
    gen.on_quit(save=False)
    assert not (tmp_path / "queue.json").exists() and gen.unfinished() == (0, 0)
    monkeypatch.setattr(gen, "_queue", [])
    assert gen.restore_queue(str(tmp_path / "queue.json")) == 0


def test_save_keeps_a_running_job_to_redo(tmp_path, monkeypatch):
    _reset_queue(monkeypatch, tmp_path)
    monkeypatch.setattr(gen, "_call", lambda *a, **k: {})
    gen.run(params=None, jobs=[{"params": {"prompt": "a"}, "label": "a"}])
    gen._queue[0]["status"] = "running"
    gen.on_quit(save=True)
    monkeypatch.setattr(gen, "_queue", [])
    assert gen.restore_queue(str(tmp_path / "queue.json")) == 1 and gen._queue[0]["status"] == "held"
