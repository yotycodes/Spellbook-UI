import os

import requests

from .writer_common import (
    WriterError, WriterRefused, WriterUnavailable,
    build_system_prompt, build_user_text, image_to_b64, parse_writer_json,
)

API_URL = "https://api.anthropic.com/v1/messages"


class ClaudeWriter:
    label = "Claude"

    def __init__(self, api_key="", model="claude-sonnet-5-5", post=requests.post, timeout=90):
        self.api_key = api_key
        self.model = model
        self.post = post
        self.timeout = timeout

    def write(self, image, tags, preset):
        key = self.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise WriterUnavailable("No Claude API key - set it in Settings > Prompt Library or ANTHROPIC_API_KEY")
        body = {
            "model": self.model,
            "max_tokens": 1024,
            "system": build_system_prompt(preset),
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_to_b64(image)}},
                    {"type": "text", "text": build_user_text(tags)},
                ],
            }],
        }
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        try:
            r = self.post(API_URL, headers=headers, json=body, timeout=self.timeout)
        except requests.RequestException as e:
            raise WriterUnavailable(f"Claude API not reachable ({e.__class__.__name__})") from e
        if r.status_code != 200:
            raise WriterUnavailable(f"Claude API error {r.status_code}: {r.text[:200]}")
        try:
            data = r.json()
        except ValueError as e:
            raise WriterError("Claude returned non-JSON body") from e
        if not isinstance(data, dict):
            data = {}
        if data.get("stop_reason") == "refusal":
            raise WriterRefused("Claude declined this image")
        text = "".join(b.get("text", "") for b in data.get("content") or [] if b.get("type") == "text")
        try:
            return parse_writer_json(text)
        except WriterError as e:
            if data.get("stop_reason") == "max_tokens":
                raise WriterError("Claude output truncated (max_tokens)") from e
            raise WriterRefused(f"Claude did not return a prompt: {text[:120]}") from e
