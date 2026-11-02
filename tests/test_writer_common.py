import base64
import io

import pytest
from PIL import Image

from lib_pl.presets import Preset
from lib_pl.writer_common import (
    WriterError, build_system_prompt, build_user_text, image_to_b64, parse_writer_json,
)

TAGS_PRESET = Preset("WAI", "tags", "masterpiece", "bad hands", {}, "Polished anime look.")
NAT_PRESET = Preset("Flux", "natural", "", "", {}, "Write sentences.")


def test_parse_plain_json():
    assert parse_writer_json('{"prompt": "1girl", "negative_extra": "", "notes": "x"}') == {
        "prompt": "1girl", "negative_extra": "", "notes": "x"}


def test_parse_fenced_and_wrapped_json():
    text = 'Here you go:\n```json\n{"prompt": "a, b", "notes": "n"}\n```\nthanks'
    assert parse_writer_json(text) == {"prompt": "a, b", "negative_extra": "", "notes": "n"}


def test_parse_invalid_raises():
    with pytest.raises(WriterError):
        parse_writer_json("I cannot help with that.")


def test_parse_missing_prompt_raises():
    with pytest.raises(WriterError):
        parse_writer_json('{"notes": "no prompt"}')


def test_system_prompt_tags_vs_natural():
    t = build_system_prompt(TAGS_PRESET)
    n = build_system_prompt(NAT_PRESET)
    assert "Danbooru" in t and "Polished anime look." in t
    assert "sentences" in n and "Write sentences." in n
    for s in (t, n):
        assert "JSON" in s and "adult" in s


def test_user_text_lists_tags():
    txt = build_user_text({"general": [("1girl", 0.99), ("smile", 0.5)], "character": [("hatsune miku", 0.9)],
                           "rating": {"general": 0.9}})
    assert "1girl, smile" in txt and "hatsune miku" in txt


def test_image_to_b64_resizes_and_is_jpeg():
    img = Image.new("RGBA", (3000, 1500), (255, 0, 0, 128))
    data = base64.b64decode(image_to_b64(img, max_side=1024))
    out = Image.open(io.BytesIO(data))
    assert out.format == "JPEG" and max(out.size) == 1024


def test_parse_prose_with_braces_before_json():
    assert parse_writer_json('Sure {not json} here: {"prompt":"a"}')["prompt"] == "a"


def test_parse_trailing_commentary_with_braces():
    assert parse_writer_json('{"prompt":"a"} (note: {x})')["prompt"] == "a"


def test_parse_nested_object_value():
    out = parse_writer_json('{"prompt":"a", "extra": {"k": {"z": 1}}}')
    assert out["prompt"] == "a"


def test_parse_list_values_coerced():
    out = parse_writer_json('{"prompt": ["a","b"], "negative_extra": ["x"], "notes": null}')
    assert out == {"prompt": "a, b", "negative_extra": "x", "notes": ""}


def test_parse_dict_prompt_raises():
    with pytest.raises(WriterError):
        parse_writer_json('{"prompt": {"x": 1}}')


def test_image_extreme_aspect_does_not_crash():
    out = Image.open(io.BytesIO(base64.b64decode(image_to_b64(Image.new("RGB", (5000, 1)), max_side=1024))))
    assert min(out.size) >= 1


def test_image_transparent_becomes_white():
    img = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    out = Image.open(io.BytesIO(base64.b64decode(image_to_b64(img)))).convert("RGB")
    assert all(c > 240 for c in out.getpixel((5, 5)))


def test_image_not_upscaled():
    out = Image.open(io.BytesIO(base64.b64decode(image_to_b64(Image.new("RGB", (100, 50)), max_side=1024))))
    assert out.size == (100, 50)


def test_user_text_empty_rating():
    assert "Rating: unknown" in build_user_text({"general": [], "rating": {}})


def test_system_prompt_demands_keeping_tagger_tags_and_bans_meta():
    t = build_system_prompt(TAGS_PRESET).lower()
    assert "keep every" in t
    for meta in ("anime", "danbooru", "tags"):
        assert meta in t
    assert "never output" in t


def test_system_prompt_lists_preset_banned_tags():
    p = Preset("WAI", "tags", "", "", {}, "Polished anime look.", ["realistic", "3d"])
    t = build_system_prompt(p)
    assert "realistic, 3d" in t


def test_user_text_marks_confident_tags_as_must_keep():
    txt = build_user_text({"general": [("1girl", 0.99), ("tongue out", 0.9), ("smile", 0.4)], "character": [],
                           "rating": {"general": 0.9}})
    must = [line for line in txt.splitlines() if line.lower().startswith("must keep")]
    assert must and "tongue out" in must[0] and "smile" not in must[0]


def test_tag_format_demands_commas():
    assert "comma" in build_system_prompt(TAGS_PRESET).lower()
