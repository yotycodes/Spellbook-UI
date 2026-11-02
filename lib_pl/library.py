import json
import math
import os
import re
import threading

import requests

from .presets import to_infotext

THEMES = {
    "Superhero / comic": r"superhero|super hero|marvel|dc comics|spider-?man|batman|superman|wonder woman|comic book|comic art|western comic|avengers|x-men|deadpool|joker|harley quinn|villain|cape",
    "Western toon / 3D cartoon": r"cartoon|toon|pixar|disney|dreamworks|3d render|cartoon network|looney|western animation|source_cartoon",
    "Chibi / cute": r"chibi|kawaii|super deformed|tiny|mascot|plush",
    "Painterly / storybook / ghibli": r"ghibli|painterly|watercolou?r|storybook|oil paint|gouache|impasto|ink wash|sumi|woodblock|ukiyo",
    "Anime action / dynamic": r"dynamic pose|action|fighting|battle|motion blur|speed lines|foreshortening|dutch angle|from below|explosion|energy|aura",
    "Dark fantasy / gothic": r"dark fantasy|gothic|horror|demon|skull|blood|witch|eldritch|occult",
    "Cyberpunk / neon": r"cyberpunk|neon|synthwave|retrowave|futuristic|mecha|robot|android",
    "Known IP (Pokemon, Naruto, DBZ...)": r"pokemon|pikachu|naruto|sasuke|itachi|goku|vegeta|dragon ball|one piece|luffy|genshin|jujutsu|demon slayer|attack on titan|evangelion|sailor moon",
}
_THEME_RX = {k: re.compile(r"\b(" + v + r")\b", re.I) for k, v in THEMES.items()}
# Tag-only themes: matched from a record's "themes" list (superhero scrape 2026-10-18), not from prompt text.
TAG_THEMES = ["Superhero – female", "Superhero – male", "Superhero – Marvel", "Superhero – DC",
              "Superhero – Anime heroes", "Superhero – Indie / other",
              # themed Civitai scrape 2026-10-19 (Chibi / cute reuses the regex theme of the same name)
              "Pin-up / fashion", "Curvy / BBW", "Fantasy", "Poses / sheets", "Toon / western", "Top Illustrious",
              # expansion 2026-10-19 (sci-fi and horror reuse the Cyberpunk / Dark fantasy regex themes)
              "Cozy / slice of life", "Mecha / robots", "Creatures / monsters", "Scenery / backgrounds",
              "Trending this month",
              # anime character scrape 2026-10-19
              "Anime – female", "Anime – male", "Anime – Naruto", "Anime – Dragon Ball", "Anime – One Piece",
              "Anime – Jujutsu Kaisen", "Anime – Demon Slayer", "Anime – Chainsaw Man", "Anime – Spy x Family",
              "Anime – Evangelion", "Anime – Sailor Moon", "Anime – Attack on Titan", "Anime – Bleach",
              "Anime – Genshin / HSR", "Anime – Frieren / fantasy", "Anime – Fate", "Anime – Other hits", "Anime – Pokemon"]
BASES = ["Illustrious", "Pony", "NoobAI", "SDXL", "Flux", "SD 1.5", "Other"]
RATINGS = ["SFW", "All (incl. mature)", "Mature only"]
SAFE = ("None", "Soft")
# Labels from Forge modules/sd_samplers_kdiffusion.py and sd_samplers_timesteps.py
SAMPLER_LABELS = [
    "DPM++ 2M", "DPM++ SDE", "DPM++ 2M SDE", "DPM++ 2M SDE Heun", "DPM++ 2S a", "DPM++ 3M SDE",
    "Euler a", "Euler", "LMS", "Heun", "DPM2", "DPM2 a", "DPM fast", "DPM adaptive", "Restart",
    "HeunPP2", "IPNDM", "IPNDM_V", "DEIS", "DDIM", "DDIM CFG++", "PLMS", "UniPC",
]
# Forge scheduler labels (modules/sd_schedulers.py), longest first for suffix matching
SCHEDULE_LABELS = ["SGM Uniform", "KL Optimal", "Exponential", "Karras", "Simple", "Normal", "Uniform", "Beta"]
SAMPLER_ALIASES = {
    "euler": "Euler", "eulerancestral": "Euler a", "eulera": "Euler a",
    "dpmpp2m": "DPM++ 2M", "dpmpp2msde": "DPM++ 2M SDE", "dpmpp3msde": "DPM++ 3M SDE",
    "dpmppsde": "DPM++ SDE", "dpmpp2sancestral": "DPM++ 2S a", "dpm2ancestral": "DPM2 a",
    "lms": "LMS", "heun": "Heun", "ddim": "DDIM", "unipc": "UniPC", "deis": "DEIS",
    "undefined": "Euler",
}


def _compact(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


_SAMPLER_MAP = {_compact(x): x for x in SAMPLER_LABELS}
_SAMPLER_MAP.update(SAMPLER_ALIASES)
_SAMPLER_MAP["lcm"] = "Euler a"  # LCM sampler is not in this Forge build
DEFAULT_SIZE = (832, 1216)


def normalize_sampler(name):
    """Return (forge sampler label, schedule label). Unknown -> ("Euler a", "")."""
    text = re.sub(r"[_\s]+", " ", (name or "").strip().lower()).strip()
    schedule = ""
    for lab in SCHEDULE_LABELS:
        if text.endswith(" " + lab.lower()):
            schedule = lab
            text = text[: -len(lab) - 1].strip()
            break
    sampler = _SAMPLER_MAP.get(_compact(text))
    if sampler is None:
        return "Euler a", ""
    return sampler, schedule


def normalize_size(size):
    try:
        w, h = [int(x) for x in str(size).lower().split("x")[:2]]
        if w <= 0 or h <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return DEFAULT_SIZE
    if max(w, h) > 2048:
        k = math.sqrt(1048576 / (w * h))
        w, h = max(64, round(w * k / 64) * 64), max(64, round(h * k / 64) * 64)
    return w, h


def base_bucket(base):
    b = base or ""
    for k in ("Pony", "Illustrious", "NoobAI"):
        if k in b:
            return k
    if "Flux" in b:
        return "Flux"
    if "SDXL" in b:
        return "SDXL"
    if b.startswith("SD 1"):
        return "SD 1.5"
    return "Other"


class Library:
    def __init__(self, folder):
        self.folder = os.path.expanduser(folder)
        self.rows, self.error, self.by_id = [], "", {}
        path = os.path.join(self.folder, "all-prompts.json")
        if not os.path.exists(path):
            self.error = f"Library file not found: {path}"
            return
        try:
            with open(path, encoding="utf-8") as f:
                rows = json.load(f)
            if not isinstance(rows, list):
                raise ValueError("expected a JSON list")
            self.by_id = {r["id"]: r for r in rows}
        except (OSError, ValueError, KeyError, TypeError) as e:
            self.error = f"Library file unreadable: {path} ({e})"
            self.by_id = {}
            return
        self.rows = rows

    def search(self, query="", base="All", theme="All", rating="SFW", limit=60):
        q = (query or "").lower().strip()
        rx = _THEME_RX.get(theme)
        out = []
        for r in self.rows:
            safe = r.get("nsfw") in SAFE
            if rating == "SFW" and not safe:
                continue
            if rating == "Mature only" and safe:
                continue
            if base not in ("All", None, "") and base_bucket(r.get("base")) != base:
                continue
            if theme not in ("All", None, "") and theme not in r.get("themes", ()) and not (rx and rx.search(r.get("prompt") or "")):
                continue
            if q and q not in (r.get("prompt") or "").lower() and q not in (r.get("hero") or ""):
                continue
            out.append(r)
            if limit and len(out) >= limit:
                break
        return out

    SORTS = ["Most reactions", "Newest", "Oldest", "Shuffle"]

    def page(self, query="", base="All", theme="All", rating="SFW", page=0, per_page=60, sort="Most reactions", seed=0,
             keep=None):
        """(rows on this page, total matches, clamped page index). Shuffle is stable for a given seed.
        keep: optional predicate(record) -> bool (collections, can-run filter)."""
        rows = self.search(query, base, theme, rating, limit=None)
        if keep is not None:
            rows = [r for r in rows if keep(r)]
        if sort == "Most reactions":
            rows = sorted(rows, key=lambda r: -(r.get("react") or 0))
        elif sort == "Newest":
            rows = sorted(rows, key=lambda r: -(r.get("id") or 0))
        elif sort == "Oldest":
            rows = sorted(rows, key=lambda r: r.get("id") or 0)
        elif sort == "Shuffle":
            import random
            rows = rows[:]
            random.Random(seed).shuffle(rows)
        last = max(0, (len(rows) - 1) // per_page)
        page = min(max(0, page), last)
        return rows[page * per_page:(page + 1) * per_page], len(rows), page


def record_settings(r):
    w, h = normalize_size(r.get("size"))
    sampler, schedule = normalize_sampler(r.get("sampler"))
    steps, cfg = r.get("steps"), r.get("cfg")
    settings = {
        "sampler": sampler,
        "scheduler": schedule,
        "steps": 30 if steps is None else steps,
        "cfg": 7 if cfg is None else cfg,
        "width": w,
        "height": h,
        "clip_skip": r.get("clip") or 0,
    }
    if base_bucket(r.get("base")) == "Flux":
        settings["distilled_cfg"] = 3.5 if cfg is None else cfg
        settings["cfg"] = 1
        settings["clip_skip"] = 0
    return r.get("prompt") or "", r.get("neg") or "", settings


def record_infotext(r):
    return to_infotext(*record_settings(r))


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


_LORA_CACHE = {}


def _lora_files(lora_dir):
    """Normalized LoRA file names, cached until the folder changes (filters call this per record)."""
    try:
        mtime = os.path.getmtime(lora_dir)
    except OSError:
        return []
    hit = _LORA_CACHE.get(lora_dir)
    if hit and hit[0] == mtime:
        return hit[1]
    files = [_norm(os.path.splitext(f)[0]) for f in os.listdir(lora_dir) if f.endswith(".safetensors")]
    _LORA_CACHE[lora_dir] = (mtime, files)
    return files


def lora_status(resources, lora_dir):
    files = _lora_files(lora_dir)
    out = []
    for x in resources:
        if (x.get("t") or "").lower() not in ("lora", "locon", "dora"):
            continue
        key = _norm(x["n"])[:24]
        if len(key) < 6:
            installed = bool(key) and key in files
        else:
            installed = any(key in f or f in key for f in files if len(f) >= 4)
        out.append((x["n"], x.get("w"), installed))
    return out


def _slim_jpeg(data, width):
    """Re-encode a downloaded rendition as a progressive JPEG at most `width` wide (about 1/3 the bytes).
    Falls back to the original bytes if Pillow can't read it."""
    try:
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        im.load()
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        if im.width > width:
            im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
        out = io.BytesIO()
        im.save(out, "JPEG", quality=82 if width <= 400 else 88, optimize=True, progressive=True)
        return out.getvalue() if out.tell() < len(data) else data
    except Exception:
        return data


class ThumbCache:
    def __init__(self, folder, get=requests.get, width=320):
        self.folder = folder
        self.get = get
        self.width = width
        self._locks = {}
        self._guard = threading.Lock()
        self._failed = set()
        os.makedirs(folder, exist_ok=True)

    def _lock(self, image_id):
        with self._guard:
            return self._locks.setdefault(image_id, threading.Lock())

    def ingest(self, image_id, src_path):
        """Build the thumbnail from a local file (imported PNG records point at their source image)."""
        dest = os.path.join(self.folder, f"{image_id}.jpg")
        with self._lock(image_id):
            if os.path.exists(dest) and os.path.getsize(dest) > 0:
                return dest
            try:
                with open(src_path, "rb") as f:
                    data = f.read()
                with open(dest, "wb") as f:
                    f.write(_slim_jpeg(data, self.width))
                return dest
            except OSError:
                return None

    def has(self, image_id):
        dest = os.path.join(self.folder, f"{image_id}.jpg")
        return os.path.exists(dest) and os.path.getsize(dest) > 0

    def path(self, image_id):
        dest = os.path.join(self.folder, f"{image_id}.jpg")
        with self._lock(image_id):
            if os.path.exists(dest) and os.path.getsize(dest) > 0:
                return dest
            if image_id in self._failed:
                return None
            got = self._fetch(image_id, dest)
            if got is None:
                self._failed.add(image_id)
            return got

    def _fetch(self, image_id, dest):
        tmp = f"{dest}.{os.getpid()}.{threading.get_ident()}.tmp"
        try:
            r = self.get("https://civitai.com/api/v1/images", params={"imageId": image_id, "nsfw": "X"}, timeout=15)
            if r.status_code != 200:
                return None
            items = r.json().get("items")
            if not items:
                return None
            item = items[0]
            url = item["url"]
            if item.get("type") == "video" or re.search(r"\.(mp4|webm)(\?|$)", url, re.I):
                return None
            thumb, n = re.subn(r"/original=true/", f"/width={self.width}/", url)
            if not n:
                return None
            img = self.get(thumb, timeout=30)
            if img.status_code != 200 or not img.content:
                return None
            if not (getattr(img, "headers", None) or {}).get("Content-Type", "").startswith("image/"):
                return None
            with open(tmp, "wb") as f:
                f.write(_slim_jpeg(img.content, self.width))
            os.replace(tmp, dest)
            return dest
        except (requests.RequestException, ValueError, KeyError, IndexError, OSError):
            return None
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass


RUNNABLE_BASES = ("Illustrious", "NoobAI")


def can_run(r, lora_dir):
    """True when the prompt targets an Illustrious-family model (your checkpoints / Krita styles) and every LoRA
    it used is installed. Checkpoints and embeddings are ignored (you'd use your own)."""
    if base_bucket(r.get("base")) not in RUNNABLE_BASES:
        return False
    return all(ok for _, _, ok in lora_status(r.get("res", []), lora_dir))
