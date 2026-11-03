"""Krita AI Diffusion styles, reused by the Generate tab: same checkpoint, LoRAs, style prompt, negative and sampler,
translated to Forge's names."""
import json
import os
import re

from .tagclean import clean

STYLES_DIR = os.path.expanduser(os.environ.get("SPELLBOOK_KRITA_STYLES")
                                or "~/Library/Application Support/krita/ai_diffusion/styles")
FALLBACK_DIR = None  # read-only second source; the server wires paths.krita_styles_dir() in. Tests stay hermetic.
SAMPLER_PRESETS = os.path.expanduser(os.environ.get("SPELLBOOK_KRITA_SAMPLERS")
                                     or "~/Library/Application Support/krita/pykrita/ai_diffusion/presets/samplers.json")

# ComfyUI sampler/scheduler ids (Krita) -> Forge labels
SAMPLERS = {"euler": "Euler", "euler_ancestral": "Euler a", "dpmpp_2m": "DPM++ 2M", "dpmpp_2m_sde": "DPM++ 2M SDE",
            "dpmpp_2m_sde_gpu": "DPM++ 2M SDE", "dpmpp_sde": "DPM++ SDE", "dpmpp_sde_gpu": "DPM++ SDE",
            "dpmpp_3m_sde": "DPM++ 3M SDE", "dpmpp_3m_sde_gpu": "DPM++ 3M SDE", "lcm": "LCM", "ddim": "DDIM",
            "uni_pc": "UniPC", "heun": "Heun", "dpm_2": "DPM2", "dpm_2_ancestral": "DPM2 a", "lms": "LMS"}
SCHEDULERS = {"karras": "Karras", "normal": "Normal", "simple": "Simple", "exponential": "Exponential",
              "sgm_uniform": "SGM Uniform", "beta": "Beta", "ddim_uniform": "Uniform"}
# Krita's built-in presets, used when the presets file can't be read
FALLBACK_PRESETS = {"Default - DPM++ 2M": ("dpmpp_2m", "karras"), "Alternative - Euler A": ("euler_ancestral", "normal"),
                    "Turbo/Lightning Merge - DPM++ SDE": ("dpmpp_sde_gpu", "karras")}


# styles renamed to "Family · Variant" (2026-10-21): old name -> new, so old gallery images and saved settings still find theirs
try:
    with open(os.path.join(os.path.dirname(__file__), "style_renames.json")) as _f:
        RENAMED = json.load(_f)
except (OSError, ValueError):
    RENAMED = {}


def current_name(name):
    return RENAMED.get(name, name)


def _presets(path=SAMPLER_PRESETS):
    try:
        with open(path) as f:
            return {k: (v.get("sampler"), v.get("scheduler")) for k, v in json.load(f).items()}
    except (OSError, ValueError, AttributeError):
        return dict(FALLBACK_PRESETS)


def load(folder=None, presets_path=None):
    """[style dict], sorted by name. Each: name, file, checkpoint, loras [(stem, weight)], style_prompt, negative,
    sampler, scheduler, steps, cfg, clip_skip, arch, origin ("spellbook" = editable; "krita" = read-only fallback).
    Defaults read the module globals at call time, so the server can repoint folders after import. The read-only
    FALLBACK_DIR (Krita's styles folder) merges only for the primary folder: its names never shadow the main
    folder's. An explicitly passed folder (tests, tools) loads alone."""
    folder = folder or STYLES_DIR
    presets_path = presets_path or SAMPLER_PRESETS
    presets = _presets(presets_path)
    out = _read(folder, presets, origin="spellbook")
    if folder == STYLES_DIR and FALLBACK_DIR \
            and os.path.abspath(os.path.expanduser(FALLBACK_DIR)) != os.path.abspath(os.path.expanduser(folder)):
        known = {s["name"].strip().lower() for s in out}
        out += [s for s in _read(FALLBACK_DIR, presets, origin="krita") if s["name"].strip().lower() not in known]
    return sorted(out, key=lambda s: s["name"].lower())


def _read(folder, presets, origin):
    """Styles from one folder (see load for the row shape)."""
    out = []
    try:
        files = sorted(f for f in os.listdir(folder) if f.endswith(".json"))
    except OSError:
        return []
    for fn in files:
        try:
            with open(os.path.join(folder, fn)) as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        sampler, scheduler = presets.get(d.get("sampler", ""), FALLBACK_PRESETS["Default - DPM++ 2M"])
        # exact round-trip: files edited by Spellbook pin the ComfyUI sampler/scheduler ids directly
        if d.get("spellbook_sampler"):
            sampler, scheduler = d["spellbook_sampler"], d.get("spellbook_scheduler") or scheduler
        ck = (d.get("checkpoints") or [""])[0]
        out.append({
            "name": d.get("name") or fn[:-5], "file": fn, "checkpoint": os.path.basename(ck), "arch": d.get("architecture", ""),
            "loras": [(os.path.splitext(os.path.basename(l["name"]))[0], float(l.get("strength", 1.0)))
                      for l in d.get("loras", []) if l.get("enabled", True) and l.get("name")],
            "style_prompt": d.get("style_prompt") or "{prompt}", "negative": d.get("negative_prompt") or "",
            "sampler": SAMPLERS.get(sampler, "Euler a"), "scheduler": SCHEDULERS.get(scheduler, "Automatic"),
            "steps": int(d.get("sampler_steps") or 25), "cfg": float(d.get("cfg_scale") or 6), "clip_skip": int(d.get("clip_skip") or 0),
            "origin": origin,
        })
    return out


def apply(style, prompt, negative=""):
    """(final prompt, final negative) the way Krita builds them: the style prompt wraps the user's prompt at {prompt},
    LoRAs are appended, negatives are joined; duplicate tags are cleaned out."""
    sp = style.get("style_prompt") or "{prompt}"
    body = sp.replace("{prompt}", prompt.strip()) if "{prompt}" in sp else ", ".join(x for x in (prompt.strip(), sp) if x)
    present = body.lower()
    loras = [f"<lora:{n}:{w:g}>" for n, w in style.get("loras", []) if f"<lora:{n.lower()}:" not in present]
    final, _ = clean(", ".join(x for x in [body] + loras if x), framing=False)
    neg, _ = clean(", ".join(x for x in (style.get("negative", ""), negative.strip()) if x), positive=False, framing=False)
    return final, neg


# ------------------------------------------------------------------ write side (styles created/edited in Spellbook)

_FORGE_LABEL = {v: k for k, v in SAMPLERS.items()}          # "Euler a" -> euler_ancestral
_SCHED_ID = {v: k for k, v in SCHEDULERS.items()}           # "Karras" -> karras


def _preset_display(comfy_sampler, comfy_scheduler, presets_path=SAMPLER_PRESETS):
    """Krita sampler-preset display name whose ids match — for on-disk compat with Krita. Best effort."""
    rev = {(v[0], v[1]): k for k, v in _presets(presets_path).items()}
    return rev.get((comfy_sampler, comfy_scheduler)) or "Default - DPM++ 2M"


def _slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "style"


def validate(d):
    """Normalize a style form payload to the row shape load() produces. Raises ValueError for bad input."""
    name = str(d.get("name") or "").strip()[:80]
    if not name:
        raise ValueError("Style needs a name.")
    sp = str(d.get("style_prompt") or "").strip()
    if "{prompt}" not in sp:
        sp = (sp.rstrip(", ") + ", {prompt}") if sp else "{prompt}"
    if d.get("sampler") not in SAMPLERS.values():
        raise ValueError(f"Unknown sampler: {d.get('sampler')}")
    scheduler = d.get("scheduler") or "Normal"
    if scheduler not in SCHEDULERS.values():
        raise ValueError(f"Unknown scheduler: {scheduler}")
    ck = os.path.basename(str(d.get("checkpoint") or "").strip())
    loras = []
    for l in (d.get("loras") or []):
        if not isinstance(l, dict) or not (str(l.get("name") or "").strip()):
            continue
        stem = os.path.splitext(os.path.basename(str(l["name"]).strip()))[0]
        try:
            w = max(0.0, min(2.0, float(l.get("strength", 1.0))))
        except (TypeError, ValueError):
            w = 1.0
        loras.append((stem, round(w, 2)))
    try:
        steps = max(4, min(150, int(d.get("steps") or 25)))
        cfg = max(1.0, min(20.0, float(d.get("cfg") or 6)))
        clip = max(0, min(5, int(d.get("clip_skip") or 0)))
    except (TypeError, ValueError):
        raise ValueError("Steps, CFG and clip skip must be numbers.")
    return {"name": name, "checkpoint": ck, "loras": loras, "style_prompt": sp,
            "negative": str(d.get("negative") or "").strip(), "sampler": d["sampler"],
            "scheduler": scheduler, "steps": steps, "cfg": round(cfg, 2), "clip_skip": clip}


def save(style, folder=None, presets_path=SAMPLER_PRESETS):
    """Write an editable style as Krita AI Diffusion JSON v2 (vendor keys carry the exact sampler ids).
    Returns the filename used. A file whose JSON name matches this style is overwritten; otherwise a
    free slot `-2`, `-3`, … is picked so no foreign style is clobbered."""
    folder = folder or STYLES_DIR
    os.makedirs(folder, exist_ok=True)
    for candidate in os.listdir(folder) if os.path.isdir(folder) else []:
        if candidate.endswith(".json"):
            try:
                with open(os.path.join(folder, candidate)) as f:
                    existing = json.load(f)
                if existing.get("name") == style["name"]:
                    fn = candidate
                    break
            except (OSError, ValueError):
                pass
    else:
        base, fn, i = _slug(style["name"]), None, 1
        while True:
            fn = f"{base}.json" if i == 1 else f"{base}-{i}.json"
            if not os.path.exists(os.path.join(folder, fn)):
                break
            i += 1
    doc = {
        "version": 2, "vae": "Checkpoint Default", "name": style["name"], "architecture": "illu",
        "checkpoints": [style["checkpoint"] or ""],
        "loras": [{"name": f"{n}.safetensors", "strength": w, "enabled": True} for n, w in style["loras"]],
        "style_prompt": style["style_prompt"], "negative_prompt": style["negative"],
        "clip_skip": style["clip_skip"], "sampler_steps": style["steps"], "cfg_scale": style["cfg"],
        "sampler": _preset_display(_FORGE_LABEL[style["sampler"]], _SCHED_ID[style["scheduler"]], presets_path),
        "spellbook_sampler": _FORGE_LABEL[style["sampler"]], "spellbook_scheduler": _SCHED_ID[style["scheduler"]],
    }
    tmp = os.path.join(folder, fn + ".tmp")
    with open(tmp, "w") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    os.replace(tmp, os.path.join(folder, fn))
    return fn


def update(fn, style, folder=None, presets_path=SAMPLER_PRESETS):
    """Overwrite the file of an existing style (rename-aware: a changed name moves the JSON).
    Returns the filename the style ended up in."""
    folder = folder or STYLES_DIR
    ok = os.path.basename(fn) == fn and fn.endswith(".json")
    p = os.path.join(folder, fn or "")
    if not ok or not os.path.isfile(p):
        raise FileNotFoundError(f"No style file: {fn}")
    os.remove(p)  # remove first so a rename frees the old slot before the new one is claimed
    return save(style, folder, presets_path)


def delete_file(fn, folder=None):
    folder = folder or STYLES_DIR
    if os.path.basename(fn) != fn or not fn.endswith(".json"):
        raise ValueError("Bad style filename.")
    p = os.path.join(folder, fn)
    if not os.path.isfile(p):
        raise FileNotFoundError(f"No style file: {fn}")
    os.remove(p)
