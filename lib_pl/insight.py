"""Interrogate extras: group tagger tags for chip editing, find similar library prompts, suggest installed LoRAs."""
import os
import re

from .character import NOT_CHARACTER, is_character_tag
from .poses import is_pose_tag

GROUPS = ["Character", "Appearance", "Pose & framing", "Expression", "Background", "Other"]

_EXPRESSION = re.compile(r"\b(smil\w*|blush\w*|grin|frown\w*|crying|tears|angry|sad|happy|surprised|embarrassed|"
                         r"expressionless|smug|pout\w*|teeth|tongue|mouth|lips|eyes|wink\w*|looking)\b")
_BACKGROUND = re.compile(r"\b(background|outdoors|indoors|sky|cloud\w*|scenery|city\w*|street|forest|tree\w*|grass|"
                         r"water|ocean|beach|night|day|sunset|sunlight|moon|stars?|room|bed\w*|window|building\w*|"
                         r"mountain\w*|snow|rain|flower\w*|nature|landscape|interior|architecture|light rays|fog)\b")
GENERIC = {"1girl", "1boy", "solo", "looking at viewer", "simple background", "white background", "breasts",
           "long hair", "short hair", "smile", "blush", "upper body", "full body", "cowboy shot", "standing"}


def group_of(tag, is_named=False):
    t = tag.lower()
    if is_named:
        return "Character"
    if is_pose_tag(t):
        return "Pose & framing"
    if "background" in t:
        return "Background"
    if t in NOT_CHARACTER:
        return "Expression"
    if is_character_tag(t):
        return "Appearance"
    if _BACKGROUND.search(t):
        return "Background"
    if _EXPRESSION.search(t):
        return "Expression"
    return "Other"


def group_tags(tags):
    """[{tag, score, group}] for named characters then general tags, highest confidence first."""
    out = [{"tag": t, "score": round(p, 3), "group": "Character"} for t, p in tags.get("character", [])]
    out += [{"tag": t, "score": round(p, 3), "group": group_of(t)} for t, p in tags.get("general", [])]
    return out


def _word_rx(tag):
    return re.compile(r"(?<![a-z0-9])" + re.escape(tag.lower()).replace(r"\ ", r"[\s_]") + r"(?![a-z0-9])")


def similar(rows, tags, limit=12, safe_only=True, safe_values=()):
    """Library rows ranked by how many of the image's tags (weighted by confidence) their prompt uses.

    tags: [(tag, score, is_named)]. Generic tags are skipped; named characters count triple."""
    probes = [(_word_rx(t), s * (3 if named else 1)) for t, s, named in tags if t.lower() not in GENERIC][:30]
    if not probes:
        return []
    scored = []
    for r in rows:
        if safe_only and r.get("nsfw") not in safe_values:
            continue
        p = (r.get("prompt") or "").lower()
        score = sum(w for rx, w in probes if rx.search(p))
        if score > 0:
            scored.append((score, r.get("react") or 0, r))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    return [r for _, _, r in scored[:limit]]


def _n(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def lora_suggestions(tag_names, lora_dir, limit=8):
    """Installed LoRA files whose name contains a tag (character names first). Returns file stems."""
    try:
        files = sorted(os.path.splitext(f)[0] for f in os.listdir(lora_dir) if f.endswith(".safetensors"))
    except OSError:
        return []
    out = []
    for tag in tag_names:
        key = _n(tag)
        if len(key) < 5 or tag.lower() in GENERIC:
            continue
        # "haruno sakura" also matches "sakura_haruno"
        parts = [_n(w) for w in re.split(r"[\s_()]+", tag) if len(_n(w)) >= 4]
        for f in files:
            fk = _n(f)
            if f in out:
                continue
            if key in fk or (len(parts) >= 2 and all(p in fk for p in parts)):
                out.append(f)
        if len(out) >= limit:
            break
    return out[:limit]
