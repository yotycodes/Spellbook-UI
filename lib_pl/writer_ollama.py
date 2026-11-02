import requests

from .writer_common import (
    WriterError, WriterUnavailable, build_system_prompt, build_user_text, image_to_b64, parse_writer_json,
)


class OllamaWriter:
    label = "Local (Ollama)"

    def __init__(self, url="http://127.0.0.1:11434", model="qwen2.5vl:7b", post=requests.post, timeout=120):
        self.url = url.rstrip("/")
        self.model = model
        self.post = post
        self.timeout = timeout

    def write(self, image, tags, preset):
        body = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "keep_alive": 0,
            "options": {"temperature": 0.4, "num_predict": 1024},
            "messages": [
                {"role": "system", "content": build_system_prompt(preset)},
                {"role": "user", "content": build_user_text(tags), "images": [image_to_b64(image)]},
            ],
        }
        try:
            r = self.post(f"{self.url}/api/chat", json=body, timeout=self.timeout)
        except (requests.exceptions.InvalidURL, requests.exceptions.MissingSchema, requests.exceptions.InvalidSchema) as e:
            raise WriterUnavailable(f"Bad URL setting: {self.url} ({e.__class__.__name__})") from e
        except requests.Timeout as e:
            raise WriterUnavailable("Ollama timed out (model may still be loading) - try again") from e
        except requests.RequestException as e:
            raise WriterUnavailable(f"Ollama not reachable at {self.url} - start the Ollama app ({e.__class__.__name__})") from e
        if r.status_code == 404:
            raise WriterUnavailable(f"Ollama model missing - run: ollama pull {self.model}")
        if r.status_code != 200:
            raise WriterUnavailable(f"Ollama error {r.status_code}: {r.text[:200]}")
        try:
            data = r.json()
        except ValueError as e:
            raise WriterError("Ollama returned non-JSON body") from e
        content = ((data.get("message") or {}) if isinstance(data, dict) else {}).get("content") or ""
        return parse_writer_json(content)
