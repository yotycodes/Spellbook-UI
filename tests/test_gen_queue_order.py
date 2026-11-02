import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "standalone"))
import gen  # noqa: E402


def _q(*models):
    return [{"id": str(i), "status": "queued", "params": {"model": m}} for i, m in enumerate(models)]


def test_loaded_model_jobs_run_first_and_the_list_shows_it():
    q = _q("b.safetensors [1]", "a.safetensors [2]", "b.safetensors [1]", "a.safetensors [2]")
    job = gen._next_job(q, "a.safetensors")
    assert job["id"] == "1" and [j["id"] for j in q] == ["1", "0", "2", "3"]


def test_fifo_when_nothing_loaded_or_no_match():
    q = _q("b", "c")
    assert gen._next_job(q, None)["id"] == "0"
    assert gen._next_job(q, "zzz")["id"] == "0"


def test_jobs_without_a_model_never_force_a_switch():
    q = _q("b", "")
    assert gen._next_job(q, "a")["id"] == "1"


def test_finished_and_held_jobs_are_skipped():
    q = _q("a", "a")
    q[0]["status"] = "done"
    q.append({"id": "h", "status": "held", "params": {"model": "a"}})
    assert gen._next_job(q, "a")["id"] == "1"
    q[1]["status"] = "done"
    assert gen._next_job(q, "a") is None


def test_models_list_does_not_rescan_when_folder_matches(tmp_path, monkeypatch):
    (tmp_path / "a.safetensors").write_bytes(b"x")
    calls = []
    listing = [{"title": "a.safetensors [1]", "filename": str(tmp_path / "a.safetensors")}]
    monkeypatch.setattr(gen, "_call", lambda path, *a, **k: calls.append(path) or listing)
    gen._models_seen["list"] = None
    assert gen._models() == listing
    assert calls == ["/sdapi/v1/sd-models"]          # nothing new on disk: no rescan


def test_models_list_serves_last_complete_list_while_rescanning(tmp_path, monkeypatch):
    (tmp_path / "a.safetensors").write_bytes(b"x")
    full = [{"title": "a.safetensors [1]", "filename": str(tmp_path / "a.safetensors")}]
    gen._models_seen["list"] = full
    assert gen._refreshing.acquire(blocking=False)
    try:
        monkeypatch.setattr(gen, "_call", lambda *a, **k: [])   # Forge mid-scan: empty list
        assert gen._models() == full
    finally:
        gen._refreshing.release()


def test_pause_after_holds_remaining_jobs(monkeypatch):
    monkeypatch.setattr(gen, "_persist", lambda: None)
    monkeypatch.setattr(gen, "_run_job", lambda j: [{"name": "img.png"}])
    gen._queue.clear()
    gen._queue.extend([
        {"id": "0", "status": "queued", "params": {"model": "m"}},
        {"id": "1", "status": "queued", "params": {"model": "m"}}
    ])
    gen._worker["pause_after"] = True
    gen._loop()
    # The loop should stop immediately when pause_after is true, setting queued to held
    assert gen._worker["thread"] is None
    assert gen._worker["pause_after"] is False
    assert gen._queue[0]["status"] == "held"
    assert gen._queue[1]["status"] == "held"


def test_reorder_pending_jobs(monkeypatch):
    monkeypatch.setattr(gen, "_persist", lambda: None)
    gen._queue.clear()
    gen._queue.extend([
        {"id": "j1", "status": "running"},
        {"id": "j2", "status": "queued"},
        {"id": "j3", "status": "queued"},
        {"id": "j4", "status": "done"},
        {"id": "j5", "status": "queued"},
    ])
    gen.reorder(["j5", "j2", "j3"])
    assert [j["id"] for j in gen._queue] == ["j1", "j5", "j2", "j4", "j3"]


