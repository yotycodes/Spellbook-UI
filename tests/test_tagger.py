import numpy as np
import pytest
from PIL import Image

from lib_pl.tagger import Tagger, escape_sd, escape_sd_text, format_tag, preprocess

CSV = "tag_id,name,category,count\n1,general,9,10\n2,explicit,9,5\n3,1girl,0,99\n4,long_hair,0,50\n5,:d,0,10\n6,hatsune_miku,4,7\n"


def test_format_tag_underscores_but_keeps_kaomoji():
    assert format_tag("long_hair") == "long hair"
    assert format_tag("^_^") == "^_^"
    assert format_tag("hatsune_miku_(cosplay)") == "hatsune miku (cosplay)"


def test_escape_sd():
    assert escape_sd("hatsune miku (cosplay)") == "hatsune miku \\(cosplay\\)"
    assert escape_sd("^_^") == "^_^"
    assert escape_sd("1girl") == "1girl"


def test_preprocess_transparent_becomes_white():
    arr = preprocess(Image.new("RGBA", (10, 10), (255, 0, 0, 0)), 448)
    assert (arr == 255).all()


def test_preprocess_tall_image_pads_left():
    arr = preprocess(Image.new("RGB", (100, 200), (255, 0, 0)), 448)
    assert (arr[0, 224, 0] == 255).all()


def test_preprocess_shape_and_bgr():
    img = Image.new("RGB", (200, 100), (255, 0, 0))  # red, wide
    arr = preprocess(img, 448)
    assert arr.shape == (1, 448, 448, 3) and arr.dtype == np.float32
    center = arr[0, 224, 224]
    assert center[2] == 255 and center[0] == 0  # BGR: red lands in channel 2
    corner = arr[0, 0, 224]
    assert (corner == 255).all()  # white padding above the wide image


class FakeSession:
    def __init__(self, probs):
        self.probs = np.array([probs], dtype=np.float32)

    def get_inputs(self):
        class I:
            name = "input"
            shape = [1, 448, 448, 3]
        return [I()]

    def run(self, outputs, feeds):
        assert feeds["input"].shape == (1, 448, 448, 3)
        return [self.probs]


def make(tmp_path, probs):
    csv = tmp_path / "selected_tags.csv"
    csv.write_text(CSV)
    return Tagger(model_path="unused", tags_csv=str(csv), session=FakeSession(probs))


def test_tag_thresholds_and_sorting(tmp_path):
    t = make(tmp_path, [0.9, 0.1, 0.98, 0.4, 0.2, 0.9])
    out = t.tag(Image.new("RGB", (64, 64)), general_threshold=0.35, character_threshold=0.85)
    assert [n for n, _ in out["general"]] == ["1girl", "long hair"]
    assert [n for n, _ in out["character"]] == ["hatsune miku"]
    assert out["rating"] == pytest.approx({"general": 0.9, "explicit": 0.1})


def test_character_below_threshold_dropped(tmp_path):
    t = make(tmp_path, [0.9, 0.1, 0.98, 0.4, 0.2, 0.5])
    assert t.tag(Image.new("RGB", (8, 8)))["character"] == []


def test_symbolic_batch_dim_shape(tmp_path):
    t = make(tmp_path, [0.9, 0.1, 0.98, 0.4, 0.2, 0.5])

    class I:
        name = "input"
        shape = ["batch_size", 448, 448, 3]
    t.session.get_inputs = lambda: [I()]
    assert [n for n, _ in t.tag(Image.new("RGB", (8, 8)))["general"]] == ["1girl", "long hair"]


def test_escape_sd_text():
    assert escape_sd_text("a (b), c \\(d\\)") == "a \\(b\\), c \\(d\\)"
    assert escape_sd_text("plain") == "plain"
