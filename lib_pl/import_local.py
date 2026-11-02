"""Library import: turn local artifacts into library records.

The primary door is **local generation-info import**: Forge / A1111 / ComfyUI write
prompt + settings into PNG text chunks, and every user owns images that way.
The sidecar record format is the library's own ``all-prompts.json`` list —
same shape for import, export and the starter shelf.

Record shape (matches Library/record(): see lib_pl/library.py):
  {"id": int, "base": "Illustrious...", "nsfw": "None|Soft|Mature|X",
   "prompt": str, "neg": str, "sampler": "DPM++ 2M Karras", "steps": 30,
   "cfg": 5, "size": "832x1216", "clip": 2, "res": [{"n","v","t","w","id"?}],
   "react": 0, "source": "civitai|png|csv|spellbook", "img": "/abs/path.png" (png only)}
"""
import csv as _csv
import hashlib
import io
import json
import os
import re

# A1111/ Forge "parameters" chunk keys worth keeping (longest first for prefix match)
PARAM_KEYS = [
    "Negative prompt", "Steps", "Sampler", "Schedule type", "CFG scale", "Seed", "Size",
    "Model hash", "Model", "Model hash hash", "Variation seed strength", "Variation seed",
    "Seed resize from", "Denoising strength", "Clip skip", "Mask blur", "Version", "Lora hashes",
    "Face restoration", "ENSD", "Eta", "CFG scale rescale", "Hires upscaler", "Hires steps",
    "Hires upscale", "Hires resize", "Skip mask above water", "Conditional mask", "Refiner switch",
    "RNG", "VAE",
] + ["Prompt"]
_PROMPT_TOKENS = re.compile(r",\s*(?=[A-Z][A-Za-z ]{2,22}\s*:\s)")


def parse_generation_info(text):
    """Parse an A1111-style 'parameters' PNG chunk into (prompt, neg, params dict).

    Settings live on the last line as 'Key: value, Key: value'; values may contain
    commas, so token *starts* are located by known-key prefixes, not by commas."""
    text = (text or "").strip()
    lines = text.split("\n")
    keys = {k.lower(): k for k in PARAM_KEYS}
    # locate each known key on any line (first occurrence wins)
    found = {}
    for i, line in enumerate(lines):
        for m in re.finditer(r"([A-Za-z][A-Za-z \-]{2,20}):\s", line):
            if m.group(1).lower() in keys and m.group(1) not in found:
                found[m.group(1)] = (i, m.start(1), m.end())
    if "Steps" not in found:  # no settings block; treat the whole text as prompt
        return text, "", {}
    out = {}
    order = sorted(found.items(), key=lambda kv: (kv[1][0], kv[1][1]))
    for idx, (k, (li, sk, sv)) in enumerate(order):
        nxt = order[idx + 1] if idx + 1 < len(order) else None
        # value runs to the next key on the same line ("+13" chars for separators)
        if nxt and nxt[1][0] == li:
            v = line_val = lines[li][sv:nxt[1][1]]
        else:
            v = lines[li][sv:]
        v = v.strip().rstrip(",").strip()
        out[k] = v
    prompt_lines = []
    neg = ""
    nk = next((k for k in out if k.lower().replace(" ", "") == "negativeprompt"), None)
    if nk:
        li, sk, _ = found[nk]
        neg = lines[li][found[nk][2]:].strip()
        prompt_lines = lines[:li]
    else:
        prompt_lines = lines[: order[0][1][0]] if order else lines
    prompt = "\n".join(prompt_lines).strip()
    return prompt, neg, out


CN_RX = re.compile(r"Cheap|cheap", re.I)


def record_from_png(path):
    """Read generation info out of a PNG's text chunks. Returns (record|None, reason)."""
    try:
        from PIL import Image
        im = Image.open(path)
        chunks = dict(getattr(im, "info", {}) or {})
        # Forge/A1111 write 'parameters'; ComfyUI writes 'prompt' (JSON workflow) or 'parameters'
        params_text = chunks.get("parameters") or ""
        comfy = {}
        if not params_text:
            raw = chunks.get("prompt") or chunks.get("Prompt") or ""
            try:
                comfy = json.loads(raw) if raw and raw.strip().startswith("{") else {}
            except ValueError:
                comfy = {}
        elif isinstance(params_text, bytes):
            params_text = params_text.decode("utf-8", "replace")
        if not params_text and not comfy:
            return None, "no generation info"
        if comfy:  # ComfyUI workflow: CLIPTextEncode nodes hold the texts
            texts = []
            for node in comfy.values():
                if node.get("class_type") == "CLIPTextEncode":
                    t = (node.get("inputs") or {}).get("text")
                    if isinstance(t, str) and t.strip():
                        texts.append(t)
            prompt = texts[0] if texts else ""
            neg = texts[1] if len(texts) > 1 else ""
            ks = next((n for n in comfy.values() if n.get("class_type") in ("KSampler", "KSamplerAdvanced",
                                                                            "SamplerCustom", "SamplerCustomAdvanced")), None)
            sched = ks.get("inputs", {}).get("scheduler") if ks else ""
            sam = ks.get("inputs", {}).get("sampler_name", "") if ks else ""
            params = {"Sampler": f"{sam} {sched}".strip().replace("_", " "),
                      "Steps": str((ks or {}).get("inputs", {}).get("steps", "")),
                      "CFG scale": str((ks or {}).get("inputs", {}).get("cfg", ""))}
        else:
            prompt, neg, params = parse_generation_info(params_text)
        if not (prompt or "").strip():
            return None, "empty prompt"
        rec = {
            "prompt": prompt.strip(), "neg": neg.strip(),
            "sampler": params.get("Sampler") or params.get("sampler") or "Euler a",
            "steps": _int(params.get("Steps")), "cfg": _f(params.get("CFG scale")),
            "size": (params.get("Size") or "").lower().replace(" ", "") or "832x1216",
            "clip": _int((params.get("Clip skip") or "").split()[0]) if params.get("Clip skip") else 0,
            "base": _base_from_model(params.get("Model") or ""),
            "nsfw": "None", "react": 0, "source": "png", "img": os.path.abspath(path),
        }
        return rec, "ok"
    except (OSError, ValueError, SyntaxError) as e:
        return None, f"unreadable ({e.__class__.__name__})"


def scrape_folder(folder, limit=1000):
    """All importable images under `folder` (PNG with generation info)."""
    out = []
    for root, _dirs, names in os.walk(os.path.expanduser(folder)):
        for n in names:
            if n.lower().endswith(".png"):
                out.append(os.path.join(root, n))
                if len(out) >= limit:
                    return out
    return out


def unique_id(existing, seed_text):
    """Collision-safe id for local records: salted hash until unused."""
    for salt in range(64):
        h = hashlib.sha1(f"{seed_text}:{salt}".encode()).hexdigest()[:11]
        rid = int(h, 16)
        if rid not in existing:
            existing.add(rid)
            return rid
    raise RuntimeError("cannot allocate a record id")


CSV_COLS = {"id": "id", "url": "url", "base": "base", "rating": "nsfw", "reactions": "react",
            "prompt": "prompt", "negative": "neg", "sampler": "sampler", "steps": "steps",
            "cfg": "cfg", "size": "size", "clip_skip": "clip", "resources": "res_txt"}
_RXT = re.compile(r"([A-Za-z]+):\s*([^|]*?)(?:\s*\(([^)]+)\))?(?:\s*@([\d.]+))?(?=\s*\||$)")
_RMAP = {"lora": "LORA", "locon": "LoCon", "dora": "DoRA", "checkpoint": "Checkpoint",
         "textualinversion": "TextualInversion", "embedding": "TextualInversion", "upscaler": "Upscaler",
         "vae": "VAE", "hypernetwork": "Hypernetwork", "wildcards": "Wildcards"}


def parse_resources(txt):
    res = []
    for m in _RXT.finditer(txt or ""):
        t, name, v, w = m.groups()
        key = re.sub(r"\W", "", t).lower()
        res.append({"t": _RMAP.get(key, t), "n": (name or "").strip(),
                    "v": (v or "").strip() or "", "w": float(w) if w else 1})
    for r_ in res:
        r_["w"] = r_["w"] if r_["w"] is not None else 1
    return res


def records_from_csv(fileobj):
    """Civitai-export style prompt CSV (id,url,base,rating,reactions,prompt,...,resources)."""
    rows = []
    reader = _csv.DictReader(fileobj)
    for row in reader:
            if not (row.get("prompt") or "").strip():
                continue
            rating = (row.get("rating") or "").strip()
            rows.append({
                "id": int(row["id"]) if str(row.get("id") or "").strip().lstrip("-").isdigit() else 0,
                "url": (row.get("url") or "").strip(),
                "base": (row.get("base") or "Other").strip(),
                "nsfw": {"None": "None", "Soft": "Soft", "Mature": "Mature"}.get(rating, "X" if rating else "None"),
                "react": int(row.get("reactions") or 0),
                "prompt": (row.get("prompt") or "").strip(),
                "neg": (row.get("negative") or "").strip(),
                "sampler": (row.get("sampler") or "Euler a").strip(),
                "steps": _int(row.get("steps")) or 30,
                "cfg": _f(row.get("cfg")) or 7, "size": (row.get("size") or "832x1216").strip(),
                "clip": _int(row.get("clip_skip")),
                "res": parse_resources(row.get("resources")),
                "source": "csv",
            })
    return rows


def merge_records(folder, records, existing_ids=None):
    """Merge records into folder/all-prompts.json, deduping by id and prompt text.
    Returns (written_count, folder). Creates the folder + sidecar as needed."""
    folder = os.path.abspath(os.path.expanduser(folder))
    os.makedirs(folder, exist_ok=True)
    sidecar = os.path.join(folder, "all-prompts.json")
    rows = []
    if os.path.exists(sidecar):
        try:
            with open(sidecar, encoding="utf-8") as f:
                rows = json.load(f)
        except (OSError, ValueError):
            rows = []
    have = {r.get("id") for r in rows}
    have_prompt = {re.sub(r"\W", "", (r.get("prompt") or "").lower())[:120] for r in rows}
    existing = existing_ids if existing_ids is not None else set()
    written = 0
    for r in records:
        pid = re.sub(r"\W", "", (r.get("prompt") or "").lower())[:120]
        if r.get("id") in have or pid in have_prompt or not r.get("prompt"):
            continue
        if not r.get("id"):  # png/recipe rows without an id
            r["id"] = unique_id(existing or set(have), f"{r['prompt'][:80]}:{r.get('img','')}")
        elif r["id"] in existing:
            r["id"] = unique_id(existing, f"{r['prompt'][:80]}:{r.get('img','')}")
        existing.add(r["id"])
        rows.append(r)
        have.add(r["id"])
        have_prompt.add(pid)
        written += 1
    tmp = sidecar + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)
    os.replace(tmp, sidecar)
    return written, folder


def _int(v):
    try:
        return int(float(str(v).split()[0].strip() or 0) // 1) if str(v).strip() not in ("", "None", "null") else 0
    except (ValueError, TypeError, IndexError):
        return 0


def _f(v):
    try:
        return float(str(v).strip() or 7)
    except (ValueError, TypeError):
        return 7.0


def _base_from_model(model_name):
    n = (model_name or "").lower()
    if "illustrious" in n or re.search(r"illus", n):
        return "Illustrious"
    if "noob" in n:
        return "NoobAI"
    if "pony" in n:
        return "Pony"
    if "flux" in n:
        return "Flux"
    if " sdxl" in n or "xl" in n or n.endswith("xl"):
        return "SDXL"
    if "sd 1" in n or "sd1" in n:
        return "SD 1.5"
    return "Other"
