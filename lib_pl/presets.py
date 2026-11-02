import json
from dataclasses import dataclass, field


@dataclass
class Preset:
    name: str
    style: str  # "tags" or "natural"
    quality_prefix: str
    negative: str
    settings: dict
    writer_rules: str = ""
    banned_tags: list = field(default_factory=list)  # never allowed in the writer's tag output
    suffix: str = ""  # tags appended after the image tags (expression/body-shape a style wants)
    sheet: dict = None  # Build-sheet config (panel_prefix, panel_suffix, panel_negative_extra, heads)
    subject_only: bool = False  # body = character tags only (no writer); prefix/suffix supply the style


def load_presets(path):
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    out = {}
    for item in raw:
        known = {k: item.get(k, "") for k in ("name", "style", "quality_prefix", "negative", "writer_rules")}
        out[item["name"]] = Preset(settings=item.get("settings", {}), banned_tags=list(item.get("banned_tags", [])),
                                   suffix=item.get("suffix", ""), sheet=item.get("sheet"), subject_only=bool(item.get("subject_only")),
                                   **known)
    return out


def merge_csv(*parts):
    seen, out = set(), []
    for part in parts:
        for tok in (part or "").split(","):
            tok = tok.strip()
            if tok and tok.lower() not in seen:
                seen.add(tok.lower())
                out.append(tok)
    return ", ".join(out)


def _num(v):
    return int(v) if isinstance(v, float) and v.is_integer() else v


def to_infotext(prompt, negative, settings):
    prompt = " ".join(prompt.split())
    negative = " ".join(negative.split())
    lines = [prompt]
    if negative:
        lines.append(f"Negative prompt: {negative}")
    p = [f"Steps: {settings['steps']}", f"Sampler: {settings['sampler']}"]
    if settings.get("scheduler"):
        p.append(f"Schedule type: {settings['scheduler']}")
    p.append(f"CFG scale: {_num(settings['cfg'])}")
    if "distilled_cfg" in settings:
        p.append(f"Distilled CFG Scale: {_num(settings['distilled_cfg'])}")
    p.append(f"Size: {settings['width']}x{settings['height']}")
    if settings.get("clip_skip"):
        p.append(f"Clip skip: {settings['clip_skip']}")
    lines.append(", ".join(p))
    return "\n".join(lines)
