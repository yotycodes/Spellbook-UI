import json
import os

from lib_pl import themes


def test_every_theme_meets_contrast_limits():
    for th in themes.THEMES:
        assert themes.check(themes.tokens(th)) == {}, th["id"]


def test_every_theme_defines_every_token():
    keys = set(themes.tokens(themes.THEMES[0]))
    for th in themes.THEMES:
        assert set(themes.tokens(th)) == keys, th["id"]


def test_generated_files_match_the_registry():
    """themes.css / themes.json are generated: rerun `python -m lib_pl.themes` after editing THEMES."""
    with open(os.path.join(themes.WEB, "themes.css")) as f:
        assert f.read() == themes.css()
    with open(os.path.join(themes.WEB, "themes.json")) as f:
        assert json.load(f) == themes.gallery()


def test_default_theme_is_plain_root_and_ids_are_unique():
    ids = [t["id"] for t in themes.THEMES]
    assert len(ids) == len(set(ids)) and themes.DEFAULT in ids
    assert ':root {' in themes.css() and f':root[data-theme="{themes.DEFAULT}"]' not in themes.css()
