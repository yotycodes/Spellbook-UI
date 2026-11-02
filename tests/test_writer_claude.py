import pytest
import requests
from PIL import Image

from lib_pl.presets import Preset
from lib_pl.writer_claude import ClaudeWriter
from lib_pl.writer_common import WriterError, WriterRefused, WriterUnavailable

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


def ok(text, stop="end_turn"):
    return Resp(200, {"content": [{"type": "text", "text": text}], "stop_reason": stop})


def test_success_request_shape():
    seen = {}

    def post(url, headers, json, timeout):
        seen.update(url=url, headers=headers, body=json)
        return ok('{"prompt": "1girl", "notes": ""}')

    out = ClaudeWriter(api_key="sk-test", model="claude-sonnet-5-5", post=post).write(IMG, TAGS, P)
    assert out["prompt"] == "1girl"
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == "sk-test"
    assert seen["headers"]["anthropic-version"] == "2023-06-01"
    body = seen["body"]
    assert body["model"] == "claude-sonnet-5-5" and body["max_tokens"] == 1024
    content = body["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[0]["source"]["media_type"] == "image/jpeg"
    assert content[1]["type"] == "text"


def test_missing_key_is_unavailable(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(WriterUnavailable, match="API key"):
        ClaudeWriter(api_key="", post=lambda **k: None).write(IMG, TAGS, P)


def test_env_key_used(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env")
    seen = {}

    def post(url, headers, json, timeout):
        seen.update(headers=headers)
        return ok('{"prompt": "x"}')

    ClaudeWriter(api_key="", post=post).write(IMG, TAGS, P)
    assert seen["headers"]["x-api-key"] == "sk-env"


def test_refusal_stop_reason():
    post = lambda url, headers, json, timeout: ok("", stop="refusal")
    with pytest.raises(WriterRefused):
        ClaudeWriter(api_key="k", post=post).write(IMG, TAGS, P)


def test_prose_answer_is_refusal():
    post = lambda url, headers, json, timeout: ok("I can't help with this image.")
    with pytest.raises(WriterRefused):
        ClaudeWriter(api_key="k", post=post).write(IMG, TAGS, P)


def test_http_error_is_unavailable():
    post = lambda url, headers, json, timeout: Resp(401, {"error": {"message": "invalid x-api-key"}})
    with pytest.raises(WriterUnavailable, match="401"):
        ClaudeWriter(api_key="k", post=post).write(IMG, TAGS, P)


def test_timeout_is_unavailable():
    def post(url, headers, json, timeout):
        raise requests.Timeout("slow")

    with pytest.raises(WriterUnavailable):
        ClaudeWriter(api_key="k", post=post).write(IMG, TAGS, P)


def test_non_json_body_is_writer_error():
    post = lambda url, headers, json, timeout: Resp(200, None, bad_json=True)
    with pytest.raises(WriterError):
        ClaudeWriter(api_key="k", post=post).write(IMG, TAGS, P)


def test_max_tokens_truncation_is_writer_error():
    post = lambda url, headers, json, timeout: ok('{"prompt": "1gi', stop="max_tokens")
    with pytest.raises(WriterError, match="truncated"):
        ClaudeWriter(api_key="k", post=post).write(IMG, TAGS, P)


def test_error_message_has_no_key():
    post = lambda url, headers, json, timeout: Resp(401, {"error": {"message": "invalid"}})
    with pytest.raises(WriterUnavailable) as ei:
        ClaudeWriter(api_key="sk-test", post=post).write(IMG, TAGS, P)
    assert "sk-test" not in str(ei.value)


def test_request_exception_has_no_key():
    def post(url, headers, json, timeout):
        raise requests.exceptions.InvalidHeader("bad header sk-test")

    with pytest.raises(WriterUnavailable) as ei:
        ClaudeWriter(api_key="sk-test", post=post).write(IMG, TAGS, P)
    assert "sk-test" not in str(ei.value)
