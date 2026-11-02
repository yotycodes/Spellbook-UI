from lib_pl.model_settings import from_meta, from_style, recommend, split_sampler


def test_split_sampler_old_and_new_metadata():
    assert split_sampler("DPM++ 2M Karras") == ("DPM++ 2M", "Karras")
    assert split_sampler("Euler a", "Automatic") == ("Euler a", None)
    assert split_sampler("DPM++ 2M", "Exponential") == ("DPM++ 2M", "Exponential")


def test_from_meta_takes_the_most_common_settings():
    imgs = [{"meta": {"sampler": "Euler a", "steps": 30, "cfgScale": 5}}] * 3 + [{"meta": {"sampler": "DPM++ 2M Karras", "steps": 20, "cfgScale": 7, "clipSkip": 1}}]
    r = from_meta(imgs, "Illustrious")
    assert (r["sampler"], r["steps"], r["cfg"], r["samples"]) == ("Euler a", 30, 5.0, 4)
    assert r["scheduler"] == "Normal" and r["clip_skip"] == 1   # base default scheduler; the one stated clip skip
    assert from_meta([{"meta": None}], "Illustrious") is None


def test_model_style_wins_and_no_hash_falls_back_to_defaults():
    styles = [{"name": "Model · Nova Anime", "checkpoint": "novaAnimeXL_ilV190.safetensors", "sampler": "Euler a", "scheduler": "Normal",
               "steps": 28, "cfg": 5.0, "clip_skip": 2, "style_prompt": "{prompt}, anime"},
              {"name": "Toon · Pin-up", "checkpoint": "novaCartoonXL_v60.safetensors", "sampler": "DPM++ 2M", "scheduler": "Karras",
               "steps": 40, "cfg": 9.0, "clip_skip": 1, "style_prompt": ""}]
    r = recommend("novaAnimeXL_ilV190.safetensors [abc123]", "x" * 64, styles)
    assert r["source"] == "style Model · Nova Anime" and r["steps"] == 28
    assert from_style("novaCartoonXL_v60.safetensors [ea20]", styles) is None   # only plain Model · styles count
    d = recommend("someIllustriousMix.safetensors", None, styles)
    assert d["sampler"] == "Euler a" and d["clip_skip"] == 2 and "default" in d["source"]
