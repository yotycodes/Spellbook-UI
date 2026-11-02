"""Krita AI Diffusion styles, reused by the Generate tab: same checkpoint, LoRAs, style prompt, negative and sampler,
translated to Forge's names."""
import json
import os

from .tagclean import clean

STYLES_DIR = os.path.expanduser(os.environ.get("SPELLBOOK_KRITA_STYLES")
                                or "~/Library/Application Support/krita/ai_diffusion/styles")
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


def load(folder=STYLES_DIR, presets_path=SAMPLER_PRESETS):
    """[style dict], sorted by name. Each: name, file, checkpoint, loras [(stem, weight)], style_prompt, negative,
    sampler, scheduler, steps, cfg, clip_skip, arch."""
    presets = _presets(presets_path)
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
        ck = (d.get("checkpoints") or [""])[0]
        out.append({
            "name": d.get("name") or fn[:-5], "file": fn, "checkpoint": os.path.basename(ck), "arch": d.get("architecture", ""),
            "loras": [(os.path.splitext(os.path.basename(l["name"]))[0], float(l.get("strength", 1.0)))
                      for l in d.get("loras", []) if l.get("enabled", True) and l.get("name")],
            "style_prompt": d.get("style_prompt") or "{prompt}", "negative": d.get("negative_prompt") or "",
            "sampler": SAMPLERS.get(sampler, "Euler a"), "scheduler": SCHEDULERS.get(scheduler, "Automatic"),
            "steps": int(d.get("sampler_steps") or 25), "cfg": float(d.get("cfg_scale") or 6), "clip_skip": int(d.get("clip_skip") or 0),
        })
    return sorted(out, key=lambda s: s["name"].lower())


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
