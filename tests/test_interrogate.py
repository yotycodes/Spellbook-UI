from PIL import Image

from lib_pl.interrogate import interrogate, tags_only_prompt
from lib_pl.presets import Preset
from lib_pl.writer_common import WriterError, WriterRefused, WriterUnavailable

S = {"sampler": "Euler a", "scheduler": "Automatic", "steps": 30, "cfg": 7, "clip_skip": 2, "width": 832, "height": 1216}
P = Preset("WAI", "tags", "masterpiece, best quality", "bad hands", S, "")
TAGS = {"general": [("1girl", 0.99), ("long hair", 0.8), ("smile", 0.5)], "character": [("hatsune miku", 0.9)],
        "rating": {"general": 0.9}}
IMG = Image.new("RGB", (8, 8))


class FakeTagger:
    def tag(self, image):
        return TAGS


class W:
    def __init__(self, label, results):
        self.label = label
        self.results = list(results)
        self.calls = 0

    def write(self, image, tags, preset):
        self.calls += 1
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


GOOD = {"prompt": "1girl, best quality, choker", "negative_extra": "extra arms", "notes": "nice"}


def test_tags_only_prompt_character_first():
    assert tags_only_prompt(TAGS) == "hatsune miku, 1girl, long hair, smile"


def test_tags_only_prompt_escapes_parens_for_sd():
    tags = {"general": [("v (gesture)", 0.9)], "character": [("hatsune miku (cosplay)", 0.9)], "rating": {}}
    assert tags_only_prompt(tags) == "hatsune miku \\(cosplay\\), v \\(gesture\\)"


def test_local_success_merges_preset():
    w = W("Local (Ollama)", [GOOD])
    r = interrogate(IMG, P, "Local (Ollama)", FakeTagger(), {"Local (Ollama)": w})
    assert r.prompt == "masterpiece, best quality, 1girl, choker, hatsune miku, long hair"
    assert r.negative == "bad hands, extra arms"
    assert r.engine_used == "Local (Ollama)"
    assert "Steps: 30" in r.infotext and r.infotext.startswith("masterpiece")
    assert "nice" in r.notes


def test_bad_json_retried_once():
    w = W("Local (Ollama)", [WriterError("bad"), GOOD])
    r = interrogate(IMG, P, "Local (Ollama)", FakeTagger(), {"Local (Ollama)": w})
    assert w.calls == 2 and r.engine_used == "Local (Ollama)"


def test_claude_refusal_falls_back_to_local():
    c = W("Claude", [WriterRefused("Claude declined this image")])
    o = W("Local (Ollama)", [GOOD])
    r = interrogate(IMG, P, "Claude", FakeTagger(), {"Claude": c, "Local (Ollama)": o})
    assert r.engine_used == "Local (Ollama)"
    assert "Claude declined" in r.notes


def test_everything_down_gives_tags_only_with_fix():
    o = W("Local (Ollama)", [WriterUnavailable("Ollama model missing - run: ollama pull qwen2.5vl:7b")])
    r = interrogate(IMG, P, "Local (Ollama)", FakeTagger(), {"Local (Ollama)": o})
    assert r.engine_used == "Tags only"
    assert r.prompt == "masterpiece, best quality, hatsune miku, 1girl, long hair, smile"
    assert r.negative == "bad hands"
    assert "ollama pull qwen2.5vl:7b" in r.notes


def test_tags_only_engine_skips_writers():
    o = W("Local (Ollama)", [GOOD])
    r = interrogate(IMG, P, "Tags only", FakeTagger(), {"Local (Ollama)": o})
    assert o.calls == 0 and r.engine_used == "Tags only"


def test_writer_prompt_parens_escaped():
    w = W("Local (Ollama)", [{"prompt": "1girl, hatsune miku (cosplay)", "negative_extra": "", "notes": ""}])
    r = interrogate(IMG, P, "Local (Ollama)", FakeTagger(), {"Local (Ollama)": w})
    assert "hatsune miku \\(cosplay\\)" in r.prompt


def test_writer_prompt_already_escaped_stays_single():
    w = W("Local (Ollama)", [{"prompt": "v \\(gesture\\)", "negative_extra": "", "notes": ""}])
    r = interrogate(IMG, P, "Local (Ollama)", FakeTagger(), {"Local (Ollama)": w})
    assert "v \\(gesture\\)" in r.prompt and "\\\\" not in r.prompt


def test_two_writer_errors_fall_to_tags_only():
    w = W("Local (Ollama)", [WriterError("a"), WriterError("b")])
    r = interrogate(IMG, P, "Local (Ollama)", FakeTagger(), {"Local (Ollama)": w})
    assert r.engine_used == "Tags only" and "Local (Ollama):" in r.notes


def test_claude_errors_twice_then_local():
    c = W("Claude", [WriterError("a"), WriterError("b")])
    o = W("Local (Ollama)", [GOOD])
    r = interrogate(IMG, P, "Claude", FakeTagger(), {"Claude": c, "Local (Ollama)": o})
    assert r.engine_used == "Local (Ollama)" and c.calls == 2


def test_natural_preset_keeps_commas_ignores_negative_extra():
    flux = Preset("Flux", "natural", "", "", S, "")
    w = W("Local (Ollama)", [{"prompt": "A girl, smiling (softly), in a park.", "negative_extra": "bad", "notes": ""}])
    r = interrogate(IMG, flux, "Local (Ollama)", FakeTagger(), {"Local (Ollama)": w})
    assert r.prompt == "A girl, smiling (softly), in a park."
    assert r.negative == ""


def test_missing_writer_noted():
    o = W("Local (Ollama)", [GOOD])
    r = interrogate(IMG, P, "Claude", FakeTagger(), {"Local (Ollama)": o})
    assert "Claude: not configured" in r.notes and r.engine_used == "Local (Ollama)"


# --- writer cleanup: banned/meta filter + restore dropped tagger tags ---

PB = Preset("WAI", "tags", "masterpiece, best quality", "bad hands", S, "", ["realistic", "3d", "photo"])
SELFIE = {"general": [("1girl", 0.99), ("tongue out", 0.9), ("selfie", 0.7), ("v", 0.65), ("choker", 0.62),
                      ("one eye closed", 0.45), ("realistic", 0.8)],
          "character": [], "rating": {"general": 0.9}}


class SelfieTagger:
    def tag(self, image):
        return SELFIE


def _run(prompt, preset=PB, tagger=None):
    w = W("Local (Ollama)", [{"prompt": prompt, "negative_extra": "", "notes": ""}])
    return interrogate(IMG, preset, "Local (Ollama)", tagger or SelfieTagger(), {"Local (Ollama)": w})


def _body(r):
    return [t.strip() for t in r.prompt.split(",")]


def test_preset_banned_tags_removed_from_writer_output():
    r = _run("1girl, realistic, 3D, tongue out, photo, selfie, v, choker")
    toks = [t.lower() for t in _body(r)]
    assert "realistic" not in toks and "3d" not in toks and "photo" not in toks
    assert "tongue out" in toks


def test_generic_meta_words_removed_for_any_tag_preset():
    r = _run("1girl, anime, danbooru, tags, Danbooru Tags, anime style, tongue out, anime coloring", preset=P)
    toks = [t.lower() for t in _body(r)]
    for junk in ("anime", "danbooru", "tags", "danbooru tags", "anime style"):
        assert junk not in toks
    assert "anime coloring" in toks  # real Danbooru tag, only exact meta tokens go


def test_banned_matches_underscores_and_escapes():
    r = _run("1girl, photo_(medium), tongue out", preset=Preset("X", "tags", "", "", S, "", ["photo (medium)"]))
    assert "photo" not in r.prompt


def test_dropped_high_confidence_tagger_tags_restored():
    r = _run("1girl, choker")
    toks = _body(r)
    assert "tongue out" in toks and "selfie" in toks and "v" in toks
    assert "one eye closed" not in toks  # below 0.6
    assert "realistic" not in toks       # banned even when tagger had it
    assert "Restored" in r.notes and "tongue out" in r.notes


def test_restore_does_not_duplicate_escaped_or_cased_tags():
    tags = {"general": [("v (gesture)", 0.9), ("Tongue Out", 0.9)], "character": [], "rating": {}}

    class T:
        def tag(self, image):
            return tags

    r = _run("v \\(gesture\\), tongue out", tagger=T())
    assert r.prompt.lower().count("tongue out") == 1 and r.prompt.count("gesture") == 1


def test_restore_includes_characters():
    r = _run("1girl", preset=P, tagger=FakeTagger())
    assert "hatsune miku" in r.prompt


def test_removed_tags_listed_in_notes():
    r = _run("1girl, anime, realistic, tongue out, selfie, v, choker")
    assert "Removed" in r.notes and "anime" in r.notes


def test_natural_preset_not_filtered_or_restored():
    flux = Preset("Flux", "natural", "", "", S, "", ["realistic"])
    r = _run("A realistic anime girl sticks her tongue out.", preset=flux)
    assert r.prompt == "A realistic anime girl sticks her tongue out."


def test_tags_only_fallback_still_drops_banned():
    w = W("Local (Ollama)", [WriterUnavailable("down")])
    r = interrogate(IMG, PB, "Local (Ollama)", SelfieTagger(), {"Local (Ollama)": w})
    assert "realistic" not in _body(r) and "tongue out" in r.prompt


def test_restore_skips_tags_in_preset_negative():
    tags = {"general": [("blurry", 0.9), ("crown", 0.9)], "character": [], "rating": {}}

    class T:
        def tag(self, image):
            return tags

    neg = Preset("WAI", "tags", "", "worst quality, Blurry", S, "")
    r = _run("crown", preset=neg, tagger=T())
    assert "blurry" not in r.prompt.lower()


def test_commaless_tag_output_retried_then_used():
    blob = {"prompt": "flower no humans pink flower blurry crown realistic depth of field", "negative_extra": "",
            "notes": ""}
    w = W("Local (Ollama)", [blob, GOOD])
    r = interrogate(IMG, P, "Local (Ollama)", FakeTagger(), {"Local (Ollama)": w})
    assert w.calls == 2 and r.engine_used == "Local (Ollama)" and "choker" in r.prompt


def test_commaless_tag_output_twice_falls_back_to_tags_only():
    blob = {"prompt": "flower no humans pink flower blurry crown realistic depth of field", "negative_extra": "",
            "notes": ""}
    w = W("Local (Ollama)", [blob, dict(blob)])
    r = interrogate(IMG, P, "Local (Ollama)", FakeTagger(), {"Local (Ollama)": w})
    assert r.engine_used == "Tags only" and "comma" in r.notes


def test_short_single_tag_output_not_treated_as_blob():
    w = W("Local (Ollama)", [{"prompt": "1girl", "negative_extra": "", "notes": ""}])
    r = interrogate(IMG, P, "Local (Ollama)", FakeTagger(), {"Local (Ollama)": w})
    assert r.engine_used == "Local (Ollama)"


def test_natural_output_without_commas_is_fine():
    flux = Preset("Flux", "natural", "", "", S, "")
    w = W("Local (Ollama)", [{"prompt": "A girl stands in a big sunny park and smiles at the camera.",
                              "negative_extra": "", "notes": ""}])
    r = interrogate(IMG, flux, "Local (Ollama)", FakeTagger(), {"Local (Ollama)": w})
    assert r.engine_used == "Local (Ollama)" and w.calls == 1


def test_echoed_preset_name_and_rules_removed():
    p = Preset("WAI-illustrious", "tags", "", "", S, "Polished anime look. Danbooru tags only. Avoid 'realistic'.")
    r = _run("1girl, WAI-illustrious, polished anime look, Danbooru tags only, danbooru-style, tongue out", preset=p)
    toks = [t.lower() for t in _body(r)]
    assert toks[:2] == ["1girl", "tongue out"]
    assert not any("danbooru" in t or "polished" in t or "wai" in t for t in toks)


def test_restored_notes_show_plain_names():
    tags = {"general": [("v (gesture)", 0.9)], "character": [], "rating": {}}

    class T:
        def tag(self, image):
            return tags

    r = _run("1girl", preset=P, tagger=T())
    assert "Restored tagger tags: v (gesture)" in r.notes and "v \\(gesture\\)" in r.prompt
