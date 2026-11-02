from lib_pl.tagclean import clean


def test_dedupes_case_underscore_and_weight():
    out, notes = clean("masterpiece, 1girl, Masterpiece, haruno_sakura, haruno sakura, best quality, (best quality:1.2)")
    assert out == "masterpiece, 1girl, haruno_sakura, (best quality:1.2)"
    assert len(notes) == 3


def test_typo_then_duplicate():
    assert clean("masterpeice, 1girl, masterpiece")[0] == "masterpiece, 1girl"


def test_framing_first_wins_positive_only():
    assert clean("1girl, upper body, smile, portrait, (full body:1.2)")[0] == "1girl, upper body, smile"
    assert clean("full body, upper body, bad hands, bad hands", positive=False)[0] == "full body, upper body, bad hands"
    assert clean("upper body, full body", framing=False)[0] == "upper body, full body"


def test_special_syntax_untouched():
    p = "<lora:zackary911_v2_IL:0.7>, 1girl, [cat:dog:0.5], {red|blue} hair, (4k, 8k, Ultra HD), 1girl"
    assert clean(p)[0] == "<lora:zackary911_v2_IL:0.7>, 1girl, [cat:dog:0.5], {red|blue} hair, (4k, 8k, Ultra HD)"


def test_segments_cleaned_separately():
    out, _ = clean("1girl, smile, smile BREAK 1girl, red hair AND 1boy, smile, smile")
    assert out == "1girl, smile BREAK 1girl, red hair AND 1boy, smile"
    assert clean("a, b\nb, c")[0] == "a, b\nb, c"


def test_empty():
    assert clean("") == ("", [])


def test_clean_can_skip_typo_fixes():
    out, notes = clean("masterpeice, 1girl, 1girl", typos=False)
    assert out == "masterpeice, 1girl" and notes == ["dup 1girl"]


def test_unclosed_paren_does_not_swallow_later_tags():
    from lib_pl.tagclean import split_top
    p = "a, b, x » (ou, plus fluide : « y, z, from behind, standing"
    assert split_top(p)[-2:] == ["from behind", "standing"]


def test_clean_removes_unclosed_brackets_and_says_so():
    from lib_pl.tagclean import clean
    out, notes = clean("a, (b, c, standing, standing")
    assert out == "a, b, c, standing" and notes[0] == "removed unclosed ("
    out, notes = clean("a, b), c")
    assert out == "a, b, c" and notes == ["removed unclosed )"]


def test_balanced_and_special_groups_untouched():
    from lib_pl.tagclean import clean, split_top
    p = "a, (b:1.2), <lora:x:0.8>, [a:b:0.5], {red|blue} hair, >_<"
    assert clean(p) == (p, [])
    assert split_top(r"\(sic\), (c, d)") == [r"\(sic\)", "(c, d)"]


def test_key_reads_weighted_and_nested_emphasis():
    from lib_pl.tagclean import key
    assert key("((crossed legs:1.4))") == "crossed legs"
    assert key("(((white background)))") == "white background"
    assert key("(HD:1.9)") == "hd"
    assert key("(a), (b)") == "(a), (b)"            # two groups, not one wrapper
    assert key(r"chi-chi \(dragon ball\)") == "chi-chi (dragon ball)"


def test_emphasis_copies_count_as_duplicates():
    from lib_pl.tagclean import clean
    out, notes = clean("((white background)), white background, pink hair")
    assert out == "((white background)), pink hair"


def test_rewrap_keeps_emphasis_and_weight():
    from lib_pl.tagclean import rewrap
    assert rewrap("((lying:1.4))", "lying on back") == "((lying on back:1.4))"
    assert rewrap("(lying)", "lying on back") == "(lying on back)"
    assert rewrap("lying", "lying on back") == "lying on back"
