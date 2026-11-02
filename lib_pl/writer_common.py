import base64
import io
import json
import re

from PIL import Image, ImageOps


class WriterError(Exception):
    """Writer answered but output was unusable (bad JSON). Retryable."""


class WriterRefused(Exception):
    """Writer declined the image."""


class WriterUnavailable(Exception):
    """Writer not reachable / not configured. Message tells the user how to fix it."""


def image_to_b64(image, max_side=1024):
    img = ImageOps.exif_transpose(image)
    if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
        rgba = img.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, rgba)
    img = img.convert("RGB")
    scale = max_side / max(img.size)
    if scale < 1:
        img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode("ascii")


_BASE = """You write prompts for Stable Diffusion Forge. You are shown one reference image plus tags from an automatic tagger.
Describe what is needed to recreate the image in the TARGET model's style: subject, body, face/expression, hair, outfit details, accessories, pose, hands, camera angle and framing, lighting, background, composition.
Translate the medium to the target: if the image is a photo and the target is anime/cartoon, write anime/cartoon tags (and vice versa).
The tagger tags are reliable. Keep EVERY tagger tag that matches the image, word for word - especially expressions, gestures and camera/framing (e.g. tongue out, one eye closed, v, selfie, choker). Only drop a tag if it is clearly wrong. Then add details the tagger missed.
Never output meta words that are not part of the picture: anime, danbooru, tags, tag, prompt, booru, model or checkpoint names, and no style words that conflict with the TARGET MODEL.
Do NOT include quality tags (masterpiece, best quality, score_9, etc.) - they are added automatically.
If a person is sexualized or suggestive, they must be clearly adult: include an adult cue (e.g. 'mature female', 'adult', or an age of 21+). Never output terms that suggest a minor.
Reply with JSON only, no prose: {"prompt": "...", "negative_extra": "comma-separated extra negatives specific to this image, or empty", "notes": "one short sentence of tips"}
Output raw JSON only - no markdown fences, no placeholder text like '...'."""

KEEP_SCORE = 0.6  # tagger tags at/above this must survive the writer (re-merged if dropped)
# Words a small VLM tends to emit that describe the task, not the image. Exact-token match only.
META_TAGS = {"anime", "anime style", "danbooru", "danbooru tags", "danbooru style", "tags", "tag", "booru",
             "prompt", "stable diffusion", "sdxl"}

_TAGS = "TARGET FORMAT: comma-separated Danbooru-style tags - put ', ' between EVERY tag (use spaces, not underscores), most important first, 25-60 tags. No sentences. No underscores and no weights like (tag:1.2)."
_NATURAL = "TARGET FORMAT: 3-6 plain English sentences in natural language. No tag lists, no weights. negative_extra must be empty."


def build_system_prompt(preset):
    fmt = _TAGS if preset.style == "tags" else _NATURAL
    text = f"{_BASE}\n\n{fmt}\nTARGET MODEL: {preset.name}\nMODEL RULES: {preset.writer_rules}"
    if preset.banned_tags:
        text += f"\nNEVER OUTPUT these words: {', '.join(preset.banned_tags)}"
    return text


def build_user_text(tags):
    general = ", ".join(t for t, _ in tags.get("general", []))
    chars = ", ".join(t for t, _ in tags.get("character", [])) or "none"
    rating = max((tags.get("rating") or {"unknown": 1}).items(), key=lambda kv: kv[1])[0]
    must = ", ".join(t for t, score in tags.get("character", []) + tags.get("general", []) if score >= KEEP_SCORE)
    return (f"Tagger tags: {general}\nCharacters detected: {chars}\nRating: {rating}\n"
            f"Must keep (high confidence): {must or 'none'}\nWrite the prompt JSON now.")


def _as_text(v):
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x).strip() for x in v)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(v)
    raise WriterError("writer JSON field has unusable type")


def parse_writer_json(text):
    text = re.sub(r"```(?:json)?", "", text or "")
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            data, _ = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and _as_text(data.get("prompt")):
            return {
                "prompt": _as_text(data["prompt"]),
                "negative_extra": _as_text(data.get("negative_extra")),
                "notes": _as_text(data.get("notes")),
            }
    raise WriterError("writer returned no usable JSON with a prompt")
