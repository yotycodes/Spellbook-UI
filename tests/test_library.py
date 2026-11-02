import json

from lib_pl.library import Library, ThumbCache, base_bucket, lora_status, normalize_sampler, normalize_size, record_infotext, record_settings

ROWS = [
    {"id": 1, "nsfw": "None", "base": "Illustrious", "react": 900, "prompt": "1girl, superhero, cape, city", "neg": "bad hands",
     "sampler": "Euler a", "steps": 30, "cfg": 7, "size": "832x1216", "clip": 2, "res": [{"n": "Detail Tweaker XL", "v": "1", "t": "LORA", "w": 0.5, "id": 9}]},
    {"id": 2, "nsfw": "X", "base": "Pony", "react": 800, "prompt": "score_9, 1girl, gothic", "neg": "", "sampler": "Euler a",
     "steps": 25, "cfg": 7, "size": "832x1216", "clip": None, "res": []},
    {"id": 3, "nsfw": "Soft", "base": "Flux.1 D", "react": 700, "prompt": "A watercolor storybook fox.", "neg": "",
     "sampler": "Undefined", "steps": 20, "cfg": 3.5, "size": "768x1344", "clip": None, "res": []},
]


def lib(tmp_path):
    p = tmp_path / "all-prompts.json"
    p.write_text(json.dumps(ROWS))
    return Library(str(tmp_path))


def test_base_bucket():
    assert base_bucket("Flux.1 D") == "Flux"
    assert base_bucket("Illustrious") == "Illustrious"
    assert base_bucket("SDXL 1.0") == "SDXL"
    assert base_bucket("Qwen") == "Other"


def test_default_search_hides_mature(tmp_path):
    assert [r["id"] for r in lib(tmp_path).search()] == [1, 3]


def test_search_query_base_theme_rating(tmp_path):
    L = lib(tmp_path)
    assert [r["id"] for r in L.search(query="cape")] == [1]
    assert [r["id"] for r in L.search(base="Flux")] == [3]
    assert [r["id"] for r in L.search(theme="Superhero / comic")] == [1]
    assert [r["id"] for r in L.search(theme="Painterly / storybook / ghibli")] == [3]
    assert [r["id"] for r in L.search(rating="All (incl. mature)")] == [1, 2, 3]
    assert [r["id"] for r in L.search(rating="Mature only")] == [2]


def test_missing_library_reports_error(tmp_path):
    L = Library(str(tmp_path / "nope"))
    assert L.rows == [] and "not found" in L.error


def test_record_infotext_maps_sampler(tmp_path):
    text = record_infotext(ROWS[0])
    assert text.startswith("1girl, superhero, cape, city\nNegative prompt: bad hands\n")
    assert "Steps: 30, Sampler: Euler a" in text and "Size: 832x1216" in text and "Clip skip: 2" in text
    flux = record_infotext(ROWS[2])
    assert "Sampler: Euler," in flux and "Negative prompt" not in flux


def test_lora_status(tmp_path):
    d = tmp_path / "Lora"
    d.mkdir()
    (d / "add_detail_XL.safetensors").write_text("")
    (d / "detail_tweaker_xl.safetensors").write_text("")
    st = lora_status(ROWS[0]["res"], str(d))
    assert st == [("Detail Tweaker XL", 0.5, True)]
    st2 = lora_status([{"n": "Gothic Neon", "t": "LORA", "w": 0.6}], str(d))
    assert st2 == [("Gothic Neon", 0.6, False)]


class R:
    def __init__(self, status, payload=None, content=b"", headers=None):
        self.headers = headers if headers is not None else {}
        self.status_code = status
        self._p = payload
        self.content = content

    def json(self):
        return self._p


def test_thumb_cache_fetches_once(tmp_path):
    calls = []

    def get(url, params=None, timeout=None):
        calls.append(url)
        if "api/v1/images" in url:
            return R(200, {"items": [{"url": "https://image.civitai.com/x/abc/original=true/abc.jpeg"}]})
        assert "/width=320/" in url
        return R(200, content=b"JPEGDATA", headers={"Content-Type": "image/jpeg"})

    tc = ThumbCache(str(tmp_path), get=get)
    p1 = tc.path(42)
    p2 = tc.path(42)
    assert p1 == p2 and open(p1, "rb").read() == b"JPEGDATA" and len(calls) == 2


def test_thumb_cache_failure_returns_none(tmp_path):
    tc = ThumbCache(str(tmp_path), get=lambda url, params=None, timeout=None: R(500))
    assert tc.path(7) is None


def test_normalize_sampler():
    n = normalize_sampler
    assert n("DPM++ 2M Karras") == ("DPM++ 2M", "Karras")
    assert n("Euler a Karras") == ("Euler a", "Karras")
    assert n("euler") == ("Euler", "")
    assert n("undefined") == ("Euler", "")
    assert n("dpmpp_2m_sde_karras") == ("DPM++ 2M SDE", "Karras")
    assert n("er_sde") == ("Euler a", "")
    assert n("DDIM") == ("DDIM", "")
    assert n("DPM++ 2M SDE SGM Uniform") == ("DPM++ 2M SDE", "SGM Uniform")
    assert n(None) == ("Euler a", "")


def test_infotext_schedule_and_size():
    r = dict(ROWS[0], sampler="DPM++ 2M Karras", size="3424x6144", steps=0, cfg=0)
    t = record_infotext(r)
    assert "Sampler: DPM++ 2M, Schedule type: Karras" in t and "Steps: 0" in t and "CFG scale: 0" in t


def test_normalize_size():
    assert normalize_size("garbage") == (832, 1216)
    assert normalize_size("0x512") == (832, 1216)
    assert normalize_size("768x1344") == (768, 1344)
    w, h = normalize_size("3424x6144")
    assert max(w, h) <= 2048 and w % 64 == 0 and h % 64 == 0
    assert abs(w / h - 3424 / 6144) / (3424 / 6144) < 0.05


def test_lora_short_name_no_substring(tmp_path):
    d = tmp_path / "Lora"
    d.mkdir()
    (d / "add_detail_XL.safetensors").write_text("")
    assert lora_status([{"n": "AI", "t": "LORA", "w": 1}], str(d)) == [("AI", 1, False)]


def test_malformed_library(tmp_path):
    (tmp_path / "all-prompts.json").write_text("{not json")
    L = Library(str(tmp_path))
    assert L.rows == [] and L.error and L.by_id == {}
    (tmp_path / "all-prompts.json").write_text("{}")
    assert Library(str(tmp_path)).error


def test_thumb_video_and_non_image_rejected(tmp_path):
    def vid(url, params=None, timeout=None):
        return R(200, {"items": [{"type": "video", "url": "https://x/original=true/a.mp4"}]})
    assert ThumbCache(str(tmp_path / "a"), get=vid).path(1) is None

    def noseg(url, params=None, timeout=None):
        return R(200, {"items": [{"url": "https://x/a.jpeg"}]})
    assert ThumbCache(str(tmp_path / "b"), get=noseg).path(1) is None

    def html(url, params=None, timeout=None):
        if "api/v1" in url:
            return R(200, {"items": [{"url": "https://x/original=true/a.jpeg"}]})
        return R(200, content=b"<html>", headers={"Content-Type": "text/html"})
    assert ThumbCache(str(tmp_path / "c"), get=html).path(1) is None


def test_thumb_failure_not_retried_and_empty_file_is_miss(tmp_path):
    calls = []

    def bad(url, params=None, timeout=None):
        calls.append(url)
        return R(500)
    tc = ThumbCache(str(tmp_path), get=bad)
    assert tc.path(5) is None and tc.path(5) is None and len(calls) == 1
    (tmp_path / "9.jpg").write_bytes(b"")
    good = ThumbCache(str(tmp_path), get=lambda url, params=None, timeout=None: R(
        200, {"items": [{"url": "https://x/original=true/a.jpeg"}]}, b"IMG", {"Content-Type": "image/jpeg"}))
    assert open(good.path(9), "rb").read() == b"IMG"


def test_flux_record_infotext_uses_distilled_cfg():
    t = record_infotext(ROWS[2])
    assert "CFG scale: 1, Distilled CFG Scale: 3.5" in t
    t2 = record_infotext(dict(ROWS[2], cfg=None))
    assert "CFG scale: 1, Distilled CFG Scale: 3.5" in t2


def test_flux_has_no_clip_skip():
    t = record_infotext(dict(ROWS[2], clip=2))
    assert "Clip skip" not in t


def test_record_settings_returns_parts():
    prompt, neg, st = record_settings(ROWS[0])
    assert prompt == "1girl, superhero, cape, city" and neg == "bad hands"
    assert st["sampler"] == "Euler a" and st["width"] == 832 and st["clip_skip"] == 2
    assert record_settings(ROWS[2])[2]["distilled_cfg"] == 3.5


def test_tag_themes_and_hero_search(tmp_path):
    import json as _j
    from lib_pl.library import Library
    rows = [{"id": 1, "nsfw": "None", "base": "Illustrious", "prompt": "peterbparker, 1boy", "hero": "spider-man",
             "themes": ["Superhero / comic", "Superhero – male", "Superhero – Marvel"]},
            {"id": 2, "nsfw": "None", "base": "Illustrious", "prompt": "1girl, dianaprince", "hero": "wonder woman",
             "themes": ["Superhero / comic", "Superhero – female", "Superhero – DC"]}]
    (tmp_path / "all-prompts.json").write_text(_j.dumps(rows))
    L = Library(str(tmp_path))
    assert [r["id"] for r in L.search(theme="Superhero – female")] == [2]
    assert [r["id"] for r in L.search(theme="Superhero / comic")] == [1, 2]
    assert [r["id"] for r in L.search("spider-man")] == [1]


def test_page_slices_and_clamps(tmp_path):
    import json as _j
    from lib_pl.library import Library
    (tmp_path / "all-prompts.json").write_text(_j.dumps([{"id": i, "nsfw": "None", "prompt": "x"} for i in range(130)]))
    L = Library(str(tmp_path))
    rows, total, page = L.page(page=1, per_page=60)
    assert total == 130 and page == 1 and [r["id"] for r in rows][:2] == [60, 61] and len(rows) == 60
    rows, total, page = L.page(page=9, per_page=60)
    assert page == 2 and len(rows) == 10
    assert L.page(page=-3)[2] == 0


def test_page_sorts(tmp_path):
    import json as _j
    from lib_pl.library import Library
    rows = [{"id": i, "nsfw": "None", "prompt": "x", "react": r} for i, r in ((1, 5), (2, 50), (3, 10))]
    (tmp_path / "all-prompts.json").write_text(_j.dumps(rows))
    L = Library(str(tmp_path))
    assert [r["id"] for r in L.page(sort="Most reactions")[0]] == [2, 3, 1]
    assert [r["id"] for r in L.page(sort="Newest")[0]] == [3, 2, 1]
    assert [r["id"] for r in L.page(sort="Oldest")[0]] == [1, 2, 3]
    a = [r["id"] for r in L.page(sort="Shuffle", seed=7)[0]]
    assert a == [r["id"] for r in L.page(sort="Shuffle", seed=7)[0]] and sorted(a) == [1, 2, 3]
