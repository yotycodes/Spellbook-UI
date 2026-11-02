import asyncio
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "standalone"))
import gen  # noqa: E402


def test_history_reuses_cache_until_a_sidecar_changes(tmp_path, monkeypatch):
    monkeypatch.setitem(gen.CFG, "out_dir", str(tmp_path))
    gen._history_cache.update(sig=None, data=None)
    meta = {"name": "20261024-000000-1.png", "seed": 1, "params": {}, "starred": False}
    path = tmp_path / "20261024-000000-1.json"
    path.write_text(json.dumps(meta))
    first = gen.history()
    second = gen.history()
    assert first is second
    assert first[0]["starred"] is False
    path.write_text(json.dumps(dict(meta, starred=True)))
    third = gen.history()
    assert third is not first
    assert third[0]["starred"] is True


def test_progress_skips_forge_preview_when_asked(monkeypatch):
    called = []

    async def fake(path, timeout=3):
        called.append(path)
        return {
            "progress": 0.5,
            "eta_relative": 1,
            "state": {"sampling_step": 1, "sampling_steps": 8, "job_no": 0},
            "current_image": "xxxx",
        }

    monkeypatch.setattr(gen, "_async_call", fake)
    gen._queue.clear()
    gen._queue.append({
        "id": "1", "status": "running", "label": "x", "started": time.time(),
        "total": 1, "params": {}, "results": [], "error": "",
    })
    skipped = asyncio.run(gen.progress(preview=False))
    assert skipped.get("preview") is None
    assert "skip_current_image=true" in called[0]
    shown = asyncio.run(gen.progress(preview=True))
    assert shown["preview"].startswith("data:image/png;base64,")
    assert "skip_current_image=false" in called[1]


def test_progress_average_uses_recent_speed_cache(monkeypatch):
    now = time.time()
    monkeypatch.setattr(gen, "_SPEED", {})
    gen._queue.clear()
    gen._queue.extend([
        # a finished Forge job: its per-image timing feeds the estimate
        {"id": "f1", "status": "done", "label": "forge", "started": now - 120, "finished": now - 60,
         "total": 2, "results": [{"name": "f1a.png"}, {"name": "f1b.png"}], "error": "", "params": {}},
    ])

    def no_forge(url, payload=None, timeout=None):
        raise gen.httpx.ConnectError("down", request=None)

    monkeypatch.setattr(gen, "_async_call", no_forge)
    p = asyncio.run(gen.progress(preview=False))
    # Forge is down, so the exposed average falls back to this session's queue (~30s)
    assert abs(p["avg_image_seconds"] - 30.0) < 0.5
    assert abs(p["avg_image_seconds_overall"] - 30.0) < 0.5
    gen._queue.clear()


def test_speed_cache_survives_a_restart(tmp_path, monkeypatch):
    q = tmp_path / "queue.json"
    q.write_text("[]")
    monkeypatch.setitem(gen.CFG, "queue_file", str(q))
    monkeypatch.setattr(gen, "_SPEED_FILE", "")
    gen._load_speed_cache()  # a fresh session: empty cache, path now known
    gen._SPEED.clear()
    gen._remember_speed("forge", 30.0)
    cache = json.load(open(tmp_path / "speed.json"))
    assert cache["forge"] == [30.0]
    # a fresh session (empty speed map) restores the cache and estimates correctly
    gen._SPEED.clear()
    gen._load_speed_cache()
    assert gen._avg_image_seconds("forge") == 30.0
    # overall estimate exists even before any job ran this session
    overall = gen._avg_image_seconds(None)
    assert overall is not None
    gen._SPEED.clear()


def test_job_finish_records_speed_without_holding_the_lock(monkeypatch, tmp_path):
    """Regression: the job-finished hook used to call _remember_speed while the worker still
    held gen._lock — which _remember_speed itself wants again. threading.Lock is not
    reentrant, so the very first successful job deadlocked the whole app: the UI froze at
    "100%" and every endpoint stopped answering. The record call must happen after the
    worker releases the lock."""
    q = tmp_path / "queue.json"
    q.write_text("[]")
    monkeypatch.setitem(gen.CFG, "queue_file", str(q))
    monkeypatch.setattr(gen, "_SPEED_FILE", "")
    gen._SPEED.clear()
    gen._queue.clear()
    gen._queue.append({"id": "t1", "label": "", "params": {"backend": "forge"}, "status": "queued",
                       "results": [], "error": "", "started": 0.0, "finished": 0.0, "total": 1})
    monkeypatch.setattr(gen, "_run_job", lambda job: [{"name": "a.png"}])
    state = {}

    def spy(backend, per_image):
        ok = gen._lock.acquire(blocking=False)  # False when the caller already holds it
        if ok:
            gen._lock.release()
        state["lock_was_nested"] = not ok
        gen._SPEED.setdefault("forge", []).append(round(float(per_image), 1))

    monkeypatch.setattr(gen, "_remember_speed", spy)
    worker_backup = dict(gen._worker)
    monkeypatch.setattr(gen, "_notify", lambda *a, **k: None)
    gen._worker.update(model_initialized=True, model="x", notify=False, pause_after=False)

    t = threading.Thread(target=gen._loop, daemon=True)
    t.start()
    t.join(10)
    assert not t.is_alive()
    assert state.get("lock_was_nested") is False, "_remember_speed ran while the worker held gen._lock"
    assert gen._SPEED["forge"]  # the finished job's speed was recorded anyway
    gen._queue.clear()
    gen._worker.clear()
    gen._worker.update(worker_backup)


def test_speed_cache_rejects_impossible_values(tmp_path, monkeypatch):
    q = tmp_path / "queue.json"
    q.write_text("[]")
    monkeypatch.setitem(gen.CFG, "queue_file", str(q))
    monkeypatch.setattr(gen, "_SPEED_FILE", "")
    gen._load_speed_cache()
    gen._SPEED.clear()
    gen._remember_speed("forge", 0)      # no time
    gen._remember_speed("forge", -5)     # negative
    gen._remember_speed("forge", 999999)  # absurd (over a day per image)
    gen._remember_speed("forge", 30.0)   # the only sane sample sticks
    assert gen._SPEED["forge"] == [30.0]
    gen._SPEED.clear()
