"""Turn a library prompt into a Krita AI Diffusion prompt.

Krita styles already add quality tags, the checkpoint and LoRAs, so the Krita prompt keeps only the subject:
quality/score/meta tags, <lora:...> tags, embeddings and BREAK are removed (LoRAs and embeddings are listed in
the notes instead). Then suggest which Krita style fits."""
import re

from .tagclean import clean, key, split_top

QUALITY = {
    "masterpiece", "best quality", "high quality", "amazing quality", "very aesthetic", "aesthetic", "absurdres",
    "highres", "high res", "newest", "recent", "ultra detailed", "ultra-detailed", "highly detailed", "extremely detailed",
    "detailed", "8k", "4k", "uhd", "hdr", "intricate details", "intricately detailed", "best aesthetic", "good quality",
    "normal quality", "official art", "sharp focus", "perfect anatomy", "beautiful", "amazing", "safe", "sensitive",
    "general", "questionable", "explicit", "rating:safe", "rating:explicit", "very awa", "year 2024", "year 2025",
}
_META = re.compile(r"^(score[_ ]\d+([_ ]up)?|source[_ ]\w+|rating[_ ]\w+|zpdxl\d*\w*|embedding:.*|easynegative|badhandv\d*|"
                   r"negative[_ ]hand.*|ng[_ ]deepnegative.*|bad[-_ ]?prompt.*|unaestheticxl.*|year \d{4})$", re.I)
_LORA = re.compile(r"<(lora|lyco|hypernet):([^:>]+)(?::([^>]+))?>", re.I)

# (style, keywords in prompt) — first match wins; order = most specific first
STYLE_RULES = [
    ("Chibi · Toon", ("chibi", "super deformed")),
    ("Sheet · Nova Toon", ("character sheet", "reference sheet", "multiple views", "turnaround")),
    ("Sketch · Rough Construction", ("sketch", "lineart", "monochrome", "pencil", "graphite")),
    ("Toon · Retro Pin-up (1950s)", ("retro", "1950s", "vintage", "pinup", "pin-up")),
    ("Toon · Disney Mid-Century", ("disney",)),
    ("Anime · Arcane", ("arcane",)),
    ("Anime · Ukiyo-e", ("ukiyo", "woodblock")),
    ("Anime · Pokémon Sugimori", ("pokemon",)),
    ("Curvy · Toon Pin-up", ("plump", "chubby", "bbw", "fat", "thick thighs", "wide hips", "curvy")),
    ("Toon · Pin-up", ("cartoon", "toon", "western")),
]
REAL = ("realistic", "photorealistic", "photo", "raw photo", "dslr", "film grain")


def suggest_style(prompt, base="", nsfw="None"):
    p = prompt.lower()
    if any(w in p for w in REAL):
        return "Model · RealVis Photo (needs the SDXL helper models in Krita) — or use Forge for photoreal"
    adult = nsfw not in ("None", "Soft", None)
    for style, words in STYLE_RULES:
        if any(re.search(rf"\b{re.escape(w)}\b", p) for w in words):
            if adult and style.startswith("Curvy"):
                return "NSFW · Boudoir Curvy (adult)"
            if adult and style == "Toon · Pin-up":
                return "NSFW · Pin-up Pose (adult)"
            if adult and style.startswith("Sheet"):
                return "NSFW · Sheet Poses (adult)"
            return style
    if adult:
        return "NSFW · Boudoir Toon (adult)"
    return "Model · WAI Anime"


def to_krita(prompt, negative="", base="", nsfw="None"):
    """Returns (krita_prompt, krita_negative, suggested_style, notes)."""
    notes = []
    loras = [(m.group(2), m.group(3) or "1") for m in _LORA.finditer(prompt or "")]
    text = _LORA.sub("", prompt or "").replace("BREAK", ",")
    kept, dropped = [], []
    for tag in split_top(text):
        k = key(tag)
        if not k or k in QUALITY or _META.match(k) or _META.match(tag.strip()):
            dropped.append(tag)
        else:
            kept.append(tag)
    out, cleaned = clean(", ".join(kept))
    neg_kept = [t for t in split_top(_LORA.sub("", negative or "")) if not _META.match(key(t)) and key(t)]
    neg, _ = clean(", ".join(neg_kept), positive=False)
    if loras:
        notes.append("LoRAs in the original (add to a style if you want them): " + ", ".join(f"{n} @ {w}" for n, w in loras))
    if dropped:
        notes.append(f"Removed {len(dropped)} quality/meta tags (your Krita style adds its own).")
    if cleaned:
        notes.append(f"Tag cleaner: {len(cleaned)} fix(es).")
    if base and "pony" in base.lower():
        notes.append("Pony prompt: works on Illustrious styles, but score_/source_ tags were removed.")
    return out, neg, suggest_style(out, base, nsfw), notes
