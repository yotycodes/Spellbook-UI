import re
from dataclasses import dataclass

from .character import character_only
from .presets import merge_csv, to_infotext
from .tagger import escape_sd, escape_sd_text
from .writer_common import KEEP_SCORE, META_TAGS, WriterError, WriterRefused, WriterUnavailable

LOCAL = "Local (Ollama)"
CLAUDE = "Claude"
TAGS_ONLY = "Tags only"
ENGINES = [LOCAL, CLAUDE, TAGS_ONLY]
CHAINS = {LOCAL: [LOCAL], CLAUDE: [CLAUDE, LOCAL], TAGS_ONLY: []}


@dataclass
class Result:
    prompt: str
    negative: str
    settings: dict
    notes: str
    engine_used: str
    infotext: str
    character: str = ""  # character-only tags (subject_only presets) for the sheet builder


def tags_only_prompt(tags):
    names = [t for t, _ in tags["character"]] + [t for t, _ in tags["general"]]
    return ", ".join(escape_sd(t) for t in names)


def _norm(tag):
    return " ".join(tag.replace("\\", "").replace("_", " ").replace("-", " ").lower().split())


def _junk_set(preset):
    junk = {_norm(b) for b in preset.banned_tags} | {_norm(m) for m in META_TAGS} | {_norm(preset.name)}
    # small writers echo MODEL RULES back as tags ("polished anime look", "danbooru tags only")
    junk |= {_norm(phrase) for phrase in re.split(r"[.;:!]", preset.writer_rules) if phrase.strip()}
    return junk


def clean_tags(body, tags, preset, restore=True):
    """Drop banned/meta tokens from a tag-style body and re-append confident tagger tags the writer dropped.

    Returns (body, removed, restored); restored holds plain tagger names."""
    junk = _junk_set(preset)
    kept, removed, seen = [], [], set()
    for tok in (t.strip() for t in body.split(",")):
        if not tok:
            continue
        key = _norm(tok)
        if key in junk or "danbooru" in key:
            removed.append(tok)
        elif key not in seen:
            seen.add(key)
            kept.append(tok)
    restored = []
    if restore:
        negative = {_norm(n) for n in preset.negative.split(",")}
        for name, score in tags.get("character", []) + tags.get("general", []):
            key = _norm(name)
            if score >= KEEP_SCORE and key not in seen and key not in junk and key not in negative:
                seen.add(key)
                restored.append(name)
    return ", ".join(kept + [escape_sd(n) for n in restored]), removed, restored


def _write_checked(writer, image, tags, preset):
    out = writer.write(image, tags, preset)
    # A comma-less run of words can't be filtered tag by tag (junk like 'realistic' hides inside it).
    if preset.style == "tags" and "," not in out["prompt"] and len(out["prompt"].split()) >= 6:
        raise WriterError("writer returned tags without commas")
    return out


def _try_writer(writer, image, tags, preset):
    try:
        return _write_checked(writer, image, tags, preset)
    except WriterError:
        return _write_checked(writer, image, tags, preset)  # one retry; a second WriterError propagates


def _subject_only(tags, preset):
    body = ", ".join(escape_sd(t) for t in character_only(tags))
    body, removed, _ = clean_tags(body, tags, preset, restore=False)
    prompt = merge_csv(preset.quality_prefix, body, preset.suffix)
    notes = [f"Engine: {TAGS_ONLY}", "Character tags only - style, pose and background come from the preset."]
    if removed:
        notes.append(f"Removed: {', '.join(removed)}")
    if preset.settings.get("checkpoint"):
        notes.append(f"Checkpoint: {preset.settings['checkpoint']}")
    return Result(prompt, preset.negative, dict(preset.settings), "\n".join(notes), TAGS_ONLY,
                  to_infotext(prompt, preset.negative, preset.settings), body)


def interrogate(image, preset, engine, tagger, writers):
    tags = tagger.tag(image)
    if preset.subject_only:
        return _subject_only(tags, preset)
    notes = []
    out, used = None, TAGS_ONLY
    for name in CHAINS.get(engine, []):
        writer = writers.get(name)
        if writer is None:
            notes.append(f"{name}: not configured")
            continue
        try:
            out = _try_writer(writer, image, tags, preset)
            used = name
            break
        except (WriterRefused, WriterUnavailable, WriterError) as e:
            notes.append(f"{name}: {e}")
    if out is None:
        body, neg_extra = tags_only_prompt(tags), ""
        if engine != TAGS_ONLY:
            notes.append("Fell back to tagger-only prompt.")
    else:
        body, neg_extra = out["prompt"], out["negative_extra"]
        if out["notes"]:
            notes.append(out["notes"])
    if preset.style == "natural":
        neg_extra = ""
        prompt = f"{preset.quality_prefix} {body}".strip() if preset.quality_prefix else body
    else:
        if out is not None:
            body = escape_sd_text(body)
        body, removed, restored = clean_tags(body, tags, preset, restore=out is not None)
        if removed:
            notes.append(f"Removed: {', '.join(removed)}")
        if restored:
            notes.append(f"Restored tagger tags: {', '.join(restored)}")
        prompt = merge_csv(preset.quality_prefix, body, preset.suffix)
    negative = merge_csv(preset.negative, neg_extra)
    notes.insert(0, f"Engine: {used}")
    return Result(prompt, negative, dict(preset.settings), "\n".join(notes), used,
                  to_infotext(prompt, negative, preset.settings), ", ".join(escape_sd(t) for t in character_only(tags)))
