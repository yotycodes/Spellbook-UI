import json

from lib_pl.favorites import Favorites
from lib_pl.library import Library, can_run


def test_collections_and_notes_persist(tmp_path):
    p = str(tmp_path / "fav.json")
    f = Favorites(p)
    f.add("Sakura sheets", 5, "great pose")
    f.add(None, 7)
    f2 = Favorites(p)
    assert f2.ids("Sakura sheets") == {5} and f2.ids(Favorites.DEFAULT) == {7}
    assert f2.note(5) == "great pose" and f2.where(5) == ["Sakura sheets"]
    f2.remove("Sakura sheets", 5)
    assert Favorites(p).ids("Sakura sheets") == set()


def test_can_run_and_keep(tmp_path):
    lora = tmp_path / "Lora"; lora.mkdir()
    (lora / "zackary911_v2_IL.safetensors").write_text("x")
    rows = [{"id": 1, "nsfw": "None", "prompt": "a", "base": "Illustrious", "res": [{"n": "zackary911_v2_IL", "t": "LORA"}]},
            {"id": 2, "nsfw": "None", "prompt": "a", "base": "Illustrious", "res": [{"n": "SomethingElseEntirely", "t": "LORA"}]},
            {"id": 3, "nsfw": "None", "prompt": "a", "base": "Pony", "res": []}]
    assert [can_run(r, str(lora)) for r in rows] == [True, False, False]
    (tmp_path / "all-prompts.json").write_text(json.dumps(rows))
    L = Library(str(tmp_path))
    assert [r["id"] for r in L.page(keep=lambda r: can_run(r, str(lora)))[0]] == [1]
