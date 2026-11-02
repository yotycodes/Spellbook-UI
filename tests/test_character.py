from PIL import Image

from lib_pl.character import character_only, is_character_tag
from lib_pl.interrogate import interrogate
from lib_pl.presets import Preset

S = {"sampler": "Euler a", "scheduler": "Automatic", "steps": 28, "cfg": 5.5, "clip_skip": 2, "width": 832, "height": 1216}
SHEET = Preset("Sheet", "tags", "<lora:x:0.7>, toon, character sheet", "3d", S, "", [], suffix="smug, wide hips",
               subject_only=True)
JESSIE = {"character": [("jessie (pokemon)", 0.95)],
          "general": [("1girl", 0.99), ("red hair", 0.95), ("long hair", 0.9), ("earrings", 0.9), ("elbow gloves", 0.9),
                      ("black gloves", 0.88), ("white skirt", 0.85), ("miniskirt", 0.8), ("crop top", 0.8),
                      ("black thighhighs", 0.8), ("black footwear", 0.8), ("midriff", 0.75), ("navel", 0.7), ("blue eyes", 0.7),
                      ("lipstick", 0.6), ("large breasts", 0.6), ("team rocket", 0.6),
                      ("white background", 0.95), ("simple background", 0.9), ("multiple views", 0.9),
                      ("smile", 0.8), ("clenched hand", 0.8), ("looking at viewer", 0.7), ("standing", 0.6),
                      ("full body", 0.6), ("solo", 0.5), ("reference sheet", 0.5), ("color guide", 0.4),
                      ("half-closed eyes", 0.5), ("open mouth", 0.5), ("hand on hip", 0.4)],
          "rating": {"general": 0.9}}


class FakeTagger:
    def tag(self, image):
        return JESSIE


class NeverWriter:
    def write(self, image, tags, preset):
        raise AssertionError("subject_only presets must not call a writer")


def test_keeps_appearance_drops_scene_pose_expression():
    out = character_only(JESSIE)
    assert out[:2] == ["jessie (pokemon)", "1girl"]
    for keep in ("red hair", "earrings", "elbow gloves", "white skirt", "miniskirt", "crop top", "black thighhighs",
                 "midriff", "blue eyes", "lipstick", "black footwear", "large breasts", "team rocket"):
        assert keep in out, keep
    for drop in ("white background", "simple background", "multiple views", "smile", "clenched hand",
                 "looking at viewer", "standing", "full body", "solo", "reference sheet", "color guide",
                 "half-closed eyes", "open mouth", "hand on hip"):
        assert drop not in out, drop


def test_is_character_tag_examples():
    assert is_character_tag("twintails") and is_character_tag("cat ears") and is_character_tag("pleated skirt")
    assert not is_character_tag("night sky") and not is_character_tag("from side") and not is_character_tag("blush")


def test_subject_only_preset_skips_writer_and_wraps_tags():
    r = interrogate(Image.new("RGB", (8, 8)), SHEET, "Local (Ollama)", FakeTagger(), {"Local (Ollama)": NeverWriter()})
    assert r.prompt.startswith("<lora:x:0.7>, toon, character sheet, jessie \\(pokemon\\), 1girl, red hair")
    assert r.prompt.endswith("smug, wide hips")
    assert "white background" not in r.prompt and "smile" not in r.prompt
    assert "Character tags only" in r.notes
