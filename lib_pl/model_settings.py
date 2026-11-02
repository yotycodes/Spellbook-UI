"""Recommended sampler / steps / CFG / clip skip for a checkpoint, so switching models in manual mode starts from
settings that suit it. Order: the checkpoint's own "Model ·" Krita style (hand-tuned), then the settings the creator
used on their Civitai sample images (most common values, looked up by the file's SHA-256), then defaults for the
model's base type. Civitai answers are cached, so each checkpoint is looked up once."""
import json
import os
import urllib.request
from collections import Counter

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"}
# base model family -> (sampler, scheduler, steps, cfg, clip skip)
DEFAULTS = {
    "illustrious": ("Euler a", "Normal", 28, 5.0, 2),
    "noobai": ("Euler a", "Normal", 28, 5.0, 2),
    "pony": ("Euler a", "Normal", 25, 7.0, 2),
    "sdxl": ("DPM++ 2M", "Karras", 30, 6.0, 1),
}
SCHEDULER_SUFFIXES = ("Karras", "Exponential", "SGM Uniform", "Simple", "Normal", "Beta", "Uniform")


def _family(base):
    b = (base or "").lower()
    return next((k for k in ("illustrious", "noobai", "pony") if k in b), "sdxl")


def split_sampler(name, schedule=None):
    """'DPM++ 2M Karras' (older A1111 metadata) -> ('DPM++ 2M', 'Karras'); a separate schedule type wins."""
    name = (name or "").strip()
    sched = schedule if schedule and schedule != "Automatic" else None
    for s in SCHEDULER_SUFFIXES:
        if name.endswith(" " + s):
            return name[: -len(s) - 1], sched or s
    return name, sched


def from_style(checkpoint, styles):
    """The checkpoint's plain "Model ·" style, if there is one."""
    base = os.path.basename(checkpoint.split(" [")[0])
    st = next((s for s in styles if s["name"].startswith("Model · ") and s["checkpoint"] == base), None)
    if not st:
        return None
    return {"sampler": st["sampler"], "scheduler": st["scheduler"], "steps": st["steps"], "cfg": st["cfg"],
            "clip_skip": st["clip_skip"], "source": f"style {st['name']}", "quality": st["style_prompt"]}


def from_meta(images, base):
    """Most common settings across the creator's sample images (their generation metadata)."""
    metas = [im.get("meta") or {} for im in images or []]
    metas = [m for m in metas if m.get("sampler") and m.get("steps") and m.get("cfgScale")]
    if not metas:
        return None
    fam = DEFAULTS[_family(base)]
    vote = lambda key: Counter(key(m) for m in metas).most_common(1)[0][0]
    sampler, sched = vote(lambda m: split_sampler(m["sampler"], m.get("Schedule type")))
    clip = Counter(m.get("clipSkip") for m in metas if m.get("clipSkip")).most_common(1)
    return {"sampler": sampler, "scheduler": sched or fam[1], "steps": int(vote(lambda m: int(m["steps"]))),
            "cfg": float(vote(lambda m: float(m["cfgScale"]))), "clip_skip": int(clip[0][0]) if clip else fam[4],
            "samples": len(metas)}


def from_civitai(sha256, timeout=20):
    req = urllib.request.Request(f"https://civitai.com/api/v1/model-versions/by-hash/{sha256}", headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.load(r)
    base = d.get("baseModel", "")
    rec = from_meta(d.get("images"), base)
    name = f"{(d.get('model') or {}).get('name', '')} {d.get('name', '')}".strip()
    if rec:
        rec["source"] = f"Civitai: {name} ({rec.pop('samples')} sample images)"
    else:
        s = DEFAULTS[_family(base)]
        rec = {"sampler": s[0], "scheduler": s[1], "steps": s[2], "cfg": s[3], "clip_skip": s[4], "source": f"{base or 'SDXL'} defaults ({name})"}
    rec["base"] = base
    return rec


def recommend(checkpoint, sha256, styles, cache_path=None):
    rec = from_style(checkpoint, styles)
    if rec:
        return rec
    cache = {}
    if cache_path:
        try:
            with open(cache_path) as f:
                cache = json.load(f)
        except (OSError, ValueError):
            pass
    if sha256 and sha256 in cache:
        return cache[sha256]
    rec = None
    if sha256:
        try:
            rec = from_civitai(sha256)
        except Exception:
            rec = None   # offline or not on Civitai: defaults, not cached, so a later try can still find it
    if rec is None:
        s = DEFAULTS["illustrious" if "illu" in checkpoint.lower() or "noob" in checkpoint.lower() else "sdxl"]
        return {"sampler": s[0], "scheduler": s[1], "steps": s[2], "cfg": s[3], "clip_skip": s[4], "source": "default settings (not found on Civitai)"}
    if cache_path:
        cache[sha256] = rec
        try:
            with open(cache_path, "w") as f:
                json.dump(cache, f, indent=1)
        except OSError:
            pass
    return rec
