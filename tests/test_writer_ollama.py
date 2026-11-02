import pytest
import requests
import requests.exceptions
from PIL import Image

from lib_pl.presets import Preset
from lib_pl.writer_common import WriterError, WriterUnavailable
from lib_pl.writer_ollama import OllamaWriter

P = Preset("WAI", "tags", "masterpiece", "", {}, "")
TAGS = {"general": [("1girl", 0.9)], "character": [], "rating": {"general": 1.0}}
IMG = Image.new("RGB", (64, 64))


class Resp:
    def __init__(self, status, payload, bad_json=False):
        self.bad_json = bad_json
        self.status_code = status
        self._p = payload
        self.text = str(payload)

    def json(self):
        if self.bad_json:
            raise ValueError("not json")
        return self._p


def test_success_builds_request_and_parses():
    calls = {}

    def post(url, json, timeout):
        calls.update(url=url, body=json, timeout=timeout)
        return Resp(200, {"message": {"content": '{"prompt": "1girl, smile", "notes": "ok"}'}})

    w = OllamaWriter(url="http://127.0.0.1:11434", model="qwen2.5vl:7b", post=post)
    out = w.write(IMG, TAGS, P)
    assert out["prompt"] == "1girl, smile"
    assert calls["url"] == "http://127.0.0.1:11434/api/chat"
    body = calls["body"]
    assert body["model"] == "qwen2.5vl:7b" and body["format"] == "json" and body["keep_alive"] == 0
    assert body["stream"] is False
    assert body["messages"][0]["role"] == "system"
    assert len(body["messages"][1]["images"]) == 1


def test_connection_error_is_unavailable():
    def post(url, json, timeout):
        raise requests.ConnectionError("refused")

    with pytest.raises(WriterUnavailable, match="Ollama"):
        OllamaWriter(post=post).write(IMG, TAGS, P)


def test_missing_model_tells_pull_command():
    def post(url, json, timeout):
        return Resp(404, {"error": "model 'qwen2.5vl:7b' not found"})

    with pytest.raises(WriterUnavailable, match="ollama pull qwen2.5vl:7b"):
        OllamaWriter(post=post).write(IMG, TAGS, P)


def test_chunked_encoding_error_is_unavailable():
    def post(url, json, timeout):
        raise requests.exceptions.ChunkedEncodingError("broken")

    with pytest.raises(WriterUnavailable):
        OllamaWriter(post=post).write(IMG, TAGS, P)


def test_bad_url_setting():
    def post(url, json, timeout):
        raise requests.exceptions.MissingSchema("no scheme")

    with pytest.raises(WriterUnavailable, match="Bad URL"):
        OllamaWriter(url="localhost:11434", post=post).write(IMG, TAGS, P)


def test_non_json_body_is_writer_error():
    post = lambda url, json, timeout: Resp(200, None, bad_json=True)
    with pytest.raises(WriterError):
        OllamaWriter(post=post).write(IMG, TAGS, P)


def test_null_message_is_writer_error():
    post = lambda url, json, timeout: Resp(200, {"message": None})
    with pytest.raises(WriterError):
        OllamaWriter(post=post).write(IMG, TAGS, P)


def test_num_predict_set():
    seen = {}

    def post(url, json, timeout):
        seen.update(json)
        return Resp(200, {"message": {"content": '{"prompt": "x"}'}})

    OllamaWriter(post=post).write(IMG, TAGS, P)
    assert seen["options"]["num_predict"] == 1024


def test_timeout_is_unavailable_with_hint():
    def post(url, json, timeout):
        raise requests.Timeout("slow")

    with pytest.raises(WriterUnavailable, match="timed out"):
        OllamaWriter(post=post).write(IMG, TAGS, P)
