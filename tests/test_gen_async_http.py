import asyncio
import os
import sys
import pytest
import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "standalone"))
import gen
from server import app
from starlette.testclient import TestClient


def test_sync_and_async_client_lifecycle():
    gen._cleanup_clients()
    sync_c = gen._get_sync_client()
    assert isinstance(sync_c, httpx.Client)
    assert not sync_c.is_closed

    # Same instance reused
    assert gen._get_sync_client() is sync_c

    # Async client
    async def check_async():
        async_c = await gen._get_async_client()
        assert isinstance(async_c, httpx.AsyncClient)
        assert not async_c.is_closed
        assert await gen._get_async_client() is async_c

    asyncio.run(check_async())
    gen._cleanup_clients()


def test_offline_and_error_formatting():
    # 404 HTTPStatusError
    req = httpx.Request("GET", "http://127.0.0.1:7860/sdapi/v1/test")
    resp_404 = httpx.Response(404, request=req)
    err_404 = httpx.HTTPStatusError("Not found", request=req, response=resp_404)
    assert "Forge is running without its API" in gen._offline(err_404)

    # 500 HTTPStatusError with a memory detail: safe manual guidance is added
    resp_500 = httpx.Response(500, request=req, json={"detail": "CUDA out of memory"})
    err_500 = httpx.HTTPStatusError("Server Error", request=req, response=resp_500)
    oom_text = gen._error_text(err_500)
    assert "Forge ran out of available memory" in oom_text
    assert "Try a smaller image size or fewer images, then retry." in oom_text
    assert "CUDA out of memory" in oom_text  # original detail is preserved

    # 500 HTTPStatusError with a non-memory detail passes through unchanged
    resp_plain = httpx.Response(500, request=req, json={"detail": "Model not loaded"})
    err_plain = httpx.HTTPStatusError("Server Error", request=req, response=resp_plain)
    assert gen._error_text(err_plain) == "Model not loaded"

    # Connection error
    conn_err = httpx.ConnectError("Connection refused", request=req)
    assert gen._error_text(conn_err) == "Forge isn't running. Click Start Forge."


def test_async_call_delegates_when_call_monkeypatched(monkeypatch):
    called = []
    monkeypatch.setattr(gen, "_call", lambda path, payload=None, timeout=10: called.append((path, payload)) or {"mock": True})

    async def run_check():
        res = await gen._async_call("/sdapi/v1/test", {"data": 123}, timeout=5)
        assert res == {"mock": True}
        assert called == [("/sdapi/v1/test", {"data": 123})]

    asyncio.run(run_check())


def test_progress_endpoint_async(monkeypatch):
    monkeypatch.setattr(gen, "_call", lambda *a, **k: {"progress": 0.42, "state": {"sampling_step": 10, "sampling_steps": 25}})
    client = TestClient(app)
    resp = client.get("/api/gen/progress")
    assert resp.status_code == 200
    data = resp.json()
    assert "running" in data
    assert "queue" in data
