"""Prompt Library — pro UI server. FastAPI JSON API over lib_pl + a static single-page app in ./web.

Run:  venv/bin/python server.py [--port 7870] [--window]
--window opens a native pywebview window (closing it quits). Old Gradio UI: app.py (kept as fallback)."""
import argparse
import functools
import io
import json
import os
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
EXT_DIR = os.path.dirname(HERE)
sys.path.insert(0, EXT_DIR)
sys.path.insert(0, HERE)

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
import httpx  # noqa: E402

from PIL import Image  # noqa: E402

from lib_pl.favorites import Favorites  # noqa: E402
from lib_pl.import_local import records_from_csv as _records_from_csv  # noqa: E402
from lib_pl import import_local  # noqa: E402
from lib_pl.interrogate import CLAUDE, ENGINES, LOCAL, TAGS_ONLY, interrogate  # noqa: E402
from lib_pl.insight import group_tags, lora_suggestions, similar  # noqa: E402
from lib_pl.krita import to_krita  # noqa: E402
from lib_pl.library import (BASES, RATINGS, SAFE, TAG_THEMES, THEMES, Library, ThumbCache, can_run,  # noqa: E402
                            lora_status, record_settings)
from lib_pl.poses import POSE_KIT, detect as detect_pose, merge as merge_pose, presets as pose_presets_func, swap as swap_pose  # noqa: E402
from lib_pl.presets import load_presets  # noqa: E402
from lib_pl.tagclean import clean, split_top  # noqa: E402
from lib_pl.tagger import Tagger, download  # noqa: E402
from lib_pl.writer_claude import ClaudeWriter  # noqa: E402
from lib_pl.writer_ollama import OllamaWriter  # noqa: E402

import paths  # noqa: E402 (single source of truth for every movable path below)

FORGE = paths.forge_dir()
APP_DIR = paths.app_data_dir()
ORIGINAL_PROTECTED_PATHS = paths.protected_paths()
SETTINGS_PATH = os.path.join(APP_DIR, "settings.json")
PRESETS_PATH = os.path.join(EXT_DIR, "presets.json")
KRITA_BRIDGE = "http://127.0.0.1:8767"
try:
    paths.write_config_template()
except Exception:  # the app must never fail to start over a config template
    pass
DEFAULTS = {
    "library_path": paths.library_dir(),
    "lora_dir": os.path.join(FORGE, "models", "Lora"),
    "tagger_dir": os.path.join(APP_DIR, "tagger", "wd-vit-tagger-v3"),
    "tagger": "wd-vit-tagger-v3",
    "general_threshold": 0.35,
    "character_threshold": 0.85,
    "ollama_url": "http://127.0.0.1:11434",
    "ollama_model": "qwen2.5vl:7b",
    "claude_model": "claude-sonnet-5-5",
}
os.makedirs(APP_DIR, exist_ok=True)


def _settings():
    s = dict(DEFAULTS)
    try:
        with open(SETTINGS_PATH) as f:
            s.update(json.load(f))
    except (OSError, ValueError):
        pass
    return s


def _beta_output_path(path):
    """Reject writes that would land in a protected location."""
    candidate = os.path.realpath(os.path.abspath(os.path.expanduser(str(path).strip())))
    for protected_path in ORIGINAL_PROTECTED_PATHS:
        protected = os.path.realpath(os.path.expanduser(protected_path))
        try:
            common = os.path.commonpath((candidate, protected))
        except ValueError:  # Different volumes
            continue
        if common == candidate or common == protected:
            raise HTTPException(400, "Choose a different folder; this path overlaps with a protected location.")
    return candidate


S = _settings()
FAV = Favorites(os.path.join(APP_DIR, "favorites.json"))
THUMBS = ThumbCache(os.path.join(APP_DIR, "thumbs"))
LARGE = ThumbCache(os.path.join(APP_DIR, "large"), width=1216)  # image viewer, fetched on demand
# Thumbnails come from Civitai on first view (~0.6 s each). Warm them in parallel as soon as a page is asked for,
# so the browser's 6-connection limit isn't the bottleneck. Newest request wins: older queued work is skipped.
_PREFETCH = ThreadPoolExecutor(max_workers=10, thread_name_prefix="thumbs")
_prefetch_gen = [0]
_prefetch_next = ThreadPoolExecutor(max_workers=2, thread_name_prefix="prefetch-next")


def _warm(ids, gen_no):
    def one(i):
        if _prefetch_gen[0] - gen_no <= 1:  # still current (or the page before it)
            THUMBS.path(i)
    for i in ids:
        if not THUMBS.has(i):
            _PREFETCH.submit(one, i)
_POSES_CACHE = None
def _get_poses():
    global _POSES_CACHE
    if _POSES_CACHE is None:
        _POSES_CACHE = pose_presets_func()
    return _POSES_CACHE
_state = {"lib": None, "tagger": None}
_lock = threading.Lock()
_pool = ThreadPoolExecutor(8)


def library():
    with _lock:
        if _state["lib"] is None:
            _state["lib"] = Library(S["library_path"])
    return _state["lib"]


def tagger():
    with _lock:
        if _state["tagger"] is None:
            model, tags = download(S["tagger"], S["tagger_dir"])
            _state["tagger"] = Tagger(model, tags)
    return _state["tagger"]


class _ThresholdTagger:
    """Runs the tagger once at low thresholds (for the chip editor) and hands interrogate the usual cut."""
    LOW_GENERAL, LOW_CHARACTER = 0.2, 0.5

    def __init__(self, t):
        self.t = t
        self.raw = None

    def tag(self, image):
        if self.raw is None:
            self.raw = self.t.tag(image, self.LOW_GENERAL, self.LOW_CHARACTER)
        g, c = S["general_threshold"], S["character_threshold"]
        return {"general": [x for x in self.raw["general"] if x[1] >= g],
                "character": [x for x in self.raw["character"] if x[1] >= c], "rating": self.raw["rating"]}


HISTORY_DIR = os.path.join(APP_DIR, "interrogations")
HISTORY_MAX = 40


def _history_save(img, result):
    import time
    os.makedirs(HISTORY_DIR, exist_ok=True)
    hid = time.strftime("%Y%m%d-%H%M%S") + f"-{random.randint(100, 999)}"
    im = img.convert("RGB")
    im.thumbnail((1536, 1536))
    im.save(os.path.join(HISTORY_DIR, hid + ".jpg"), quality=90)
    result = dict(result, id=hid, time=time.time())
    with open(os.path.join(HISTORY_DIR, hid + ".json"), "w") as f:
        json.dump(result, f)
    stems = sorted({os.path.splitext(n)[0] for n in os.listdir(HISTORY_DIR)}, reverse=True)
    for old in stems[HISTORY_MAX:]:
        for ext in (".jpg", ".json"):
            try:
                os.remove(os.path.join(HISTORY_DIR, old + ext))
            except OSError:
                pass
    return result


def _history_path(hid, ext):
    if not re.fullmatch(r"[0-9]{8}-[0-9]{6}-[0-9]{3}", hid or ""):
        raise HTTPException(400, "Bad id")
    p = os.path.join(HISTORY_DIR, hid + ext)
    if not os.path.exists(p):
        raise HTTPException(404, "Not found")
    return p


def _bridge(path, payload, timeout=8):
    try:
        resp = httpx.post(f"{KRITA_BRIDGE}{path}", json=payload, timeout=httpx.Timeout(timeout, connect=2.0))
        return resp.json()
    except Exception:
        return {"ok": False, "error": "Krita isn't reachable. Open Krita with a document (and the AI Prompt Bridge add-on)."}


def _canvas(st):
    w, h = st["width"], st["height"]
    return "832×1216" if h > w else ("1216×832" if w > h else "1024×1024")


app = FastAPI(title="Spellbook UI", docs_url=None, redoc_url=None)


@app.middleware("http")
async def _revalidate_app_files(request, call_next):
    """The UI files change with every update; make the window revalidate them instead of reusing a stale copy."""
    resp = await call_next(request)
    path = request.url.path
    if not path.startswith("/api/") and (path == "/" or path.endswith((".html", ".js", ".css"))):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


STYLES_DIR = paths.styles_dir()
KRITA_STYLES_DIR = paths.krita_styles_dir()  # read-only fallback source: styles Krita users already have

from lib_pl import kstyles as _kstyles  # noqa: E402
_kstyles.STYLES_DIR = STYLES_DIR          # single control plane: the library reads the dirs the config picked
_kstyles.FALLBACK_DIR = KRITA_STYLES_DIR


def style_names():
    """Style names, sorted (Spellbook's styles folder first; legacy Krita styles merged in)."""
    import gen  # noqa: E402  (module-level import of gen happens later; lazy here)
    return [s["name"] for s in gen.styles()]


# ------------------------------------------------------------------ styles API: the manager UI's backend
def _styles_payload():
    import gen
    rows = [dict(s, editable=s["origin"] == "spellbook") for s in gen.styles()]
    return {"styles": rows, "dir": STYLES_DIR,
            "krita_dir": KRITA_STYLES_DIR if any(r["origin"] == "krita" for r in rows) else ""}


@app.get("/api/styles")
def styles_list():
    """Full style detail for the manager: rows from load() + editable flag + folder(s)."""
    return _styles_payload()


def _style_write(filename, body):
    """Create (filename=None) or update; validate first, guard names, write and report."""
    import gen
    try:
        st = _kstyles.validate(body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    taken = {s["name"]: s for s in gen.styles() if s["origin"] == "spellbook"}
    old = taken.get(st["name"])
    if old and old["file"] != (filename or ""):
        raise HTTPException(409, f"A style named \u201c{st['name']}\u201d already exists. Rename one of them.")
    try:
        fn = _kstyles.update(filename, st) if filename else _kstyles.save(st)
    except FileNotFoundError:
        raise HTTPException(404, "That style file is gone — reload and try again.")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "file": fn, "name": st["name"], **_styles_payload()}


@app.post("/api/styles")
def style_create(st: dict = Body(...)):
    return _style_write(None, st)


@app.post("/api/styles/{filename}")
def style_save(filename: str, st: dict = Body(...)):
    return _style_write(filename, st)


@app.delete("/api/styles/{filename}")
def style_delete(filename: str):
    import gen
    row = next((s for s in gen.styles() if s["file"] == filename), None)
    if row and row["origin"] != "spellbook":
        raise HTTPException(400, "That style lives in Krita's folder and is read-only — copy it here first.")
    try:
        _kstyles.delete_file(filename)
    except FileNotFoundError:
        raise HTTPException(404, "That style file is gone — reload and try again.")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {**_styles_payload(), "ok": True}


_HEROES = {}


def _heroes():
    """Character names in the library with counts, most prompts first (search autocomplete + palette)."""
    L = library()
    if _HEROES.get("n") != len(L.rows):
        c = {}
        for r in L.rows:
            if r.get("hero"):
                c[r["hero"]] = c.get(r["hero"], 0) + 1
        _HEROES.update(n=len(L.rows), list=[[h, n] for h, n in sorted(c.items(), key=lambda kv: -kv[1])])
    return _HEROES["list"]


_TAGS = []


def _tag_list():
    """Danbooru tags from the tagger's vocabulary (general + character), most used first."""
    if not _TAGS:
        import csv
        path = os.path.join(S["tagger_dir"], S["tagger"], "selected_tags.csv")
        try:
            with open(path, newline="", encoding="utf-8") as f:
                rows = [(r["name"], int(r.get("count") or 0), r["category"]) for r in csv.DictReader(f) if r["category"] in ("0", "4")]
        except OSError:
            rows = []
        rows.sort(key=lambda x: -x[1])
        _TAGS.extend((n.replace("_", " ") if len(n) > 3 else n, c, cat) for n, c, cat in rows)
    return _TAGS


@app.get("/api/tags")
def tags(q: str = "", limit: int = 10):
    q = q.strip().lower().replace("_", " ")
    if len(q) < 2:
        return []
    pre, mid = [], []
    for n, c, cat in _tag_list():
        if n.startswith(q):
            pre.append(n)
        elif len(mid) < limit and f" {q}" in f" {n}":
            mid.append(n)
        if len(pre) >= limit:
            break
    return (pre + mid)[:limit]


@app.get("/api/character/{name}")
def character(name: str, rating: str = "SFW"):
    """Character page: counts, matching installed LoRAs, Krita styles that fit their prompts, top prompts."""
    L = library()
    key = name.strip().lower()
    rows = [r for r in L.rows if (r.get("hero") or "").lower() == key]
    if not rows:
        raise HTTPException(404, "Not a character in the library")
    safe = [r for r in rows if r.get("nsfw") in SAFE]
    use = safe if rating == "SFW" else rows
    tally = {}
    for r in use[:200]:
        st = to_krita(r["prompt"], r.get("neg", ""), r.get("base") or "", r.get("nsfw"))[2].split(" (needs")[0]
        tally[st] = tally.get(st, 0) + 1
    uni = {}
    for r in rows:
        if r.get("universe"):
            uni[r["universe"]] = uni.get(r["universe"], 0) + 1
    known = set(gen.styles() and [x["name"] for x in gen.styles()])
    styles = [{"name": k, "count": v, "installed": k in known} for k, v in sorted(tally.items(), key=lambda kv: -kv[1])[:4]]
    return {"hero": rows[0]["hero"], "total": len(rows), "sfw": len(safe), "universe": max(uni, key=uni.get) if uni else "",
            "gender": rows[0].get("gender") or "", "loras": lora_suggestions([rows[0]["hero"]], S["lora_dir"]),
            "styles": styles, "ids": [r["id"] for r in sorted(use, key=lambda r: -(r.get("react") or 0))][:480]}


@app.get("/api/health")
def health():
    return {"ok": True, "app": "spellbook", "version": "0.3.26"}


@app.get("/api/meta")
def meta():
    presets = list(load_presets(PRESETS_PATH))
    poses = [{"label": k, "key": v["key"], "tags": v["tags"], "note": v["note"], "canvas": v["canvas"],
              "has_skeleton": bool(v["skeleton"])} for k, v in _get_poses().items()]
    return {"bases": ["All"] + BASES, "themes": ["All"] + list(THEMES) + TAG_THEMES, "ratings": RATINGS,
            "sorts": Library.SORTS, "collections": FAV.names(), "presets": presets, "engines": ENGINES,
            "default_engine": TAGS_ONLY, "poses": poses, "heroes": _heroes(), "styles": style_names(), "library_size": len(library().rows)}


@app.get("/api/search")
def search(q: str = "", base: str = "All", theme: str = "All", rating: str = "SFW", sort: str = "Most reactions",
           per_page: int = 120, page: int = 0, collection: str = "All", runnable: bool = False, seed: int = 0):
    L = library()
    if L.error:  # fresh machines start with no library: a structured marker, not an error, drives the import empty state
        return {"total": 0, "page": 0, "pages": 0, "per_page": per_page, "items": [], "library_error": L.error}
    checks = []
    if collection and collection != "All":
        ids = FAV.ids(collection)
        checks.append(lambda r: r["id"] in ids)
    if runnable:
        checks.append(lambda r: can_run(r, S["lora_dir"]))
    keep = (lambda r: all(c(r) for c in checks)) if checks else None
    per_page = max(12, min(int(per_page), 480))
    rows, total, page = L.page(q, base, theme, rating, page, per_page, sort, seed, keep)
    _prefetch_gen[0] += 1
    gen_no = _prefetch_gen[0]
    _warm([r["id"] for r in rows], gen_no)

    def _next():  # warm the next page too; failures here are always safe to drop
        try:
            nxt, _, _ = L.page(q, base, theme, rating, page + 1, per_page, sort, seed, keep)
            _warm([r["id"] for r in nxt], gen_no)
        except Exception:
            pass
    _prefetch_next.submit(_next)
    return {"total": total, "page": page, "pages": max(1, -(-total // per_page)), "per_page": per_page,
            "items": [{"id": r["id"], "base": r.get("base") or "?", "react": r.get("react") or 0, "nsfw": r.get("nsfw"),
                       "fav": bool(FAV.where(r["id"]))} for r in rows]}


@app.get("/api/thumb/{rid}")
def thumb(rid: int):
    p = THUMBS.path(rid)
    if not p:  # local imports render from their own source image
        r = library().by_id.get(rid)
        if r and r.get("img") and os.path.isfile(os.path.expanduser(r["img"])):
            p = THUMBS.ingest(rid, os.path.expanduser(r["img"]))
    if not p:
        raise HTTPException(404)
    return FileResponse(p, headers={"Cache-Control": "max-age=604800"})


def _refresh_library():
    with _lock:
        _state["lib"] = None


def _existing_ids():
    """Every id already in any library folder on disk + used by local paths elsewhere."""
    ids = set()
    try:
        p = os.path.join(paths.library_dir(), "all-prompts.json")
        if os.path.exists(p):
            ids |= {r.get("id") for r in json.load(open(p, encoding="utf-8"))}
    except (OSError, ValueError):
        pass
    return ids


@app.post("/api/library/import/pngs")
def import_pngs(body: dict = Body(...)):
    """Scan a folder for PNGs carrying generation info (Forge/A1111/ComfyUI) and import them as records."""
    folder = str(body.get("folder") or "").strip()
    if not folder:
        raise HTTPException(400, "No folder given.")
    folder_x = os.path.expanduser(folder)
    if not os.path.isdir(folder_x):
        raise HTTPException(400, f"Folder not found: {folder_x}")
    files = import_local.scrape_folder(folder_x)
    if not files:
        return {"imported": 0, "folder": folder_x, "note": "No .png files found in that folder."}
    records, skipped = [], 0
    existing = _existing_ids()
    for path in files:
        rec, reason = import_local.record_from_png(path)
        if rec:
            records.append(rec)
        else:
            skipped += 1
    n, dest = import_local.merge_records(S["library_path"], records, existing_ids=existing)
    _refresh_library()
    note = "No generation info found in the PNGs (Forge writes it when 'Save' keeps prompts)." if not n else ""
    return {"imported": n, "skipped": skipped, "folder": folder_x, "library": dest, "note": note}


@app.post("/api/library/import/csv")
def import_csv(file: UploadFile = File(...)):
    data = file.file.read()
    try:
        rows = _records_from_csv(io.TextIOWrapper(io.BytesIO(data), encoding="utf-8-sig"))
    except Exception:
        raise HTTPException(400, "Could not read that CSV file.")
    n, dest = import_local.merge_records(S["library_path"], rows, existing_ids=_existing_ids())
    _refresh_library()
    return {"imported": n, "rows": len(rows), "library": dest}


@app.post("/api/library/import/json")
def import_json_file(file: UploadFile = File(...)):
    try:
        rows = json.load(io.TextIOWrapper(io.BytesIO(file.file.read()), encoding="utf-8"))
    except Exception:
        raise HTTPException(400, "Could not read that JSON file.")
    if not isinstance(rows, list):
        raise HTTPException(400, "Expected a JSON list of records.")
    n, dest = import_local.merge_records(S["library_path"], rows, existing_ids=_existing_ids())
    _refresh_library()
    return {"imported": n, "rows": len(rows), "library": dest}


@app.post("/api/library/starter-shelf")
def starter_shelf():
    """One click: copy the shipped starter shelf (50 runnable prompts) into the user's library."""
    shelf_path = os.path.join(EXT_DIR, "starter-shelf.json")
    if not os.path.exists(shelf_path):
        raise HTTPException(500, "Starter shelf file is missing from this install.")
    try:
        rows = json.load(open(shelf_path, encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise HTTPException(500, f"Starter shelf unreadable: {e}")
    n, dest = import_local.merge_records(S["library_path"], rows, existing_ids=_existing_ids())
    _refresh_library()
    return {"imported": n, "total": len(rows), "library": dest}


@app.get("/api/library/export.json")
def library_export():
    sidecar = os.path.join(os.path.expanduser(S["library_path"]), "all-prompts.json")
    if not os.path.exists(sidecar):
        raise HTTPException(404, "No library to export yet — add prompts first.")
    return FileResponse(sidecar, filename="spellbook-library.json",
                        headers={"Cache-Control": "no-store"})


@app.post("/api/library/reset")
def library_reset(confirm: str = Body("", embed=True), clear_favorites: bool = Body(True, embed=True)):
    """Empty the prompt library: move all-prompts.json (and favorites.json) into a timestamped backup
    under the app data folder, then start fresh — no restart needed. Requires confirm == "RESET"."""
    if confirm != "RESET":
        raise HTTPException(400, 'Type "RESET" to confirm: this empties the prompt library (a backup is saved first).')
    import shutil
    from datetime import datetime
    folder = os.path.abspath(os.path.expanduser(S["library_path"]))
    backup_dir = os.path.join(APP_DIR, "library-backups",
                              "reset-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    cleared = 0
    moved = []
    os.makedirs(backup_dir, exist_ok=True)
    sidecar = os.path.join(folder, "all-prompts.json")
    if os.path.exists(sidecar):
        try:
            with open(sidecar, encoding="utf-8") as f:
                cleared = len(json.load(f))
        except (OSError, ValueError):
            cleared = 0
        os.replace(sidecar, os.path.join(backup_dir, "all-prompts.json"))
        moved.append("all-prompts.json")
    favorites_removed = 0
    favorites_cleared = False
    if clear_favorites:
        fav_path = os.path.join(APP_DIR, "favorites.json")
        if os.path.exists(fav_path):
            shutil.copyfile(fav_path, os.path.join(backup_dir, "favorites.json"))
        favorites_removed = FAV.clear()
        favorites_cleared = True
        # Thumbnail caches are keyed by prompt id; id collisions after a re-import make stale files junk.
        for cache in (THUMBS, LARGE):
            shutil.rmtree(cache.folder, ignore_errors=True)
    _refresh_library()
    return {"ok": True, "cleared": cleared, "backups_moved": moved, "backup_dir": backup_dir,
            "favorites_cleared": favorites_cleared, "favorites_removed": favorites_removed}


@app.get("/api/large/{rid}")
def large(rid: int):
    p = LARGE.path(rid) or THUMBS.path(rid)
    if not p:
        raise HTTPException(404)
    return FileResponse(p, headers={"Cache-Control": "max-age=604800"})


@app.get("/api/record/{rid}")
def record(rid: int):
    r = library().by_id.get(rid)
    if r is None:
        raise HTTPException(404, "Not in library")
    st = record_settings(r)[2]
    kp, kn, style, notes = to_krita(r["prompt"], r.get("neg", ""), r.get("base") or "", r.get("nsfw"))
    pose, _ = detect_pose(kp)
    return {
        "id": rid, "prompt": r["prompt"], "negative": r.get("neg", ""), "base": r.get("base") or "?",
        "nsfw": r.get("nsfw"), "react": r.get("react") or 0, "hero": r.get("hero"), "themes": r.get("themes", []),
        "source": r.get("source", "civitai"),
        "settings": {k: st.get(k) for k in ("sampler", "scheduler", "steps", "cfg", "width", "height", "clip_skip", "distilled_cfg") if st.get(k) is not None},
        "loras": [{"name": n, "weight": w, "installed": ok} for n, w, ok in lora_status(r.get("res", []), S["lora_dir"])],
        "runnable": can_run(r, S["lora_dir"]),
        "krita": {"prompt": kp, "negative": kn, "style": style.split(" (needs")[0], "style_note": style, "notes": notes,
                  "canvas": _canvas(st)},
        "pose_tags": pose, "tags": [t for t in split_top(kp) if 2 < len(t) < 40][:48],
        "collections": FAV.where(rid), "note": FAV.note(rid),
        "url": r.get("url") or (f"https://civitai.com/images/{rid}" if r.get("source", "civitai") == "civitai" else ""),
    }


@app.post("/api/favorites")
def fav_add(id: int = Body(...), collection: str = Body(Favorites.DEFAULT), note: str | None = Body(None)):
    name = FAV.add(collection, id, note)
    return {"collection": name, "collections": FAV.names(), "in": FAV.where(id)}


@app.post("/api/favorites/remove")
def fav_remove(id: int = Body(...), collection: str = Body(...)):
    FAV.remove(collection, id)
    return {"collections": FAV.names(), "in": FAV.where(id)}


@app.get("/api/collections")
def collections():
    return [{"name": n, "count": len(FAV.ids(n)), "cover": next(iter(FAV.data["collections"][n][-1:]), None)} for n in FAV.names()]


@app.post("/api/collections/delete")
def collection_delete(name: str = Body(..., embed=True)):
    if name == Favorites.DEFAULT:
        raise HTTPException(400, "The default collection can't be deleted.")
    with FAV._lock:
        ids = FAV.data["collections"].pop(name, None) or []
        FAV._save()
    return {"collections": FAV.names(), "ids": ids}


@app.post("/api/collections/restore")
def collection_restore(name: str = Body(..., embed=True), ids: list = Body(default=[])):
    """Put back a collection the user just deleted (toast Undo): exact membership included."""
    name = (name or "").strip()
    if not name or name == Favorites.DEFAULT:
        raise HTTPException(400, "Restore needs a collection name.")
    with FAV._lock:
        FAV.data["collections"][name] = [int(i) for i in ids if str(i).lstrip("-").isdigit()]
        FAV._save()
    return {"collections": FAV.names()}


@app.post("/api/pose/merge")
def pose_merge(prompt: str = Body(...), pose: str = Body(""), drop: list = Body([]), facing_filter: bool = Body(True),
               view: list = Body(None)):
    """Generate's pose control: first take out the tags the previous pose added (`drop`), then add `pose` and
    remove the prompt tags that conflict with it (and, with facing_filter, words that face the body the other
    way). Returns the new prompt + what was removed / added."""
    from lib_pl.poses import facing_filter as face_filter, pose_facing
    from lib_pl.tagclean import key as tag_key
    gone = {tag_key(t) for t in drop}
    base = ", ".join(t for t in split_top(prompt or "") if tag_key(t) not in gone)
    if not pose.strip():
        return {"prompt": clean(base)[0], "removed": [], "added": []}
    out, removed, added = merge_pose(base, pose)
    from lib_pl.poses import pose_wins
    out, in_groups = pose_wins(out, pose)          # pose words inside (( )) groups
    removed += [t for t in in_groups if t not in removed]
    if facing_filter:
        tags_ = view if view is not None else pose   # view: the pose's full tags
        out, turned = face_filter(out, *pose_facing(tags_), pose_tags=tags_)
        removed += [t for t in turned if t not in added]
        added = [t for t in added if t not in turned]
    return {"prompt": out, "removed": removed, "added": added}


@app.post("/api/pose/swap")
def pose_swap(prompt: str = Body(...), pose: str = Body(...)):
    return {"prompt": swap_pose(prompt, pose)}


_PACKS = {"mtime": None, "items": [], "by_id": {}}
PACKS_DIR = os.path.join(POSE_KIT, "packs")
MINE_DIR = os.path.join(PACKS_DIR, "_mine")          # skeletons extracted from your own images
POSE_PREFS = os.path.join(APP_DIR, "pose_prefs.json")  # starred + recently used poses


def _mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0


def pose_packs():
    """Every browsable pose: Civitai packs (index.json + features.json from Pose-Kit tools), your Pose Kit presets
    and poses extracted from your images (_mine/index.json). Items carry tags and a joint vector for similarity."""
    files = [os.path.join(PACKS_DIR, "index.json"), os.path.join(PACKS_DIR, "features.json"), os.path.join(MINE_DIR, "index.json")]
    stamp = tuple(_mtime(f) for f in files)
    if stamp == _PACKS["mtime"]:
        return _PACKS
    def load(p, default):
        try:
            with open(p) as f:
                return json.load(f)
        except (OSError, ValueError):
            return default
    items, feats = load(files[0], []), load(files[1], {})
    for x in items:
        f = feats.get(x["id"], {})
        x["tags"], x["v"] = f.get("tags", []), f.get("v")
    for k, v in _get_poses().items():                       # Pose Kit presets join the browser as their own category
        if not v.get("skeleton"):
            continue
        pid = "kit-" + v["key"]
        f = _kit_features.get(pid)
        if f is None:
            from lib_pl.pose_features import analyze
            f = _kit_features[pid] = analyze(v["skeleton"])
        w, h = (int(n) for n in (v.get("canvas") or "832x1216").split("x"))
        items.append({"id": pid, "cat": "kit", "pack": "My Pose Kit", "label": k, "path": v["skeleton"], "abs": True,
                      "w": w, "h": h, "tags": f["tags"], "v": f["v"], "kit_tags": v["tags"],
                      "nsfw": "boudoir" in k.lower() or "/boudoir/" in v["skeleton"].lower()})
    for x in load(files[2], []):
        items.append({**x, "cat": "mine", "pack": "From your images"})
    from lib_pl.pose_features import NONSTANDARD_PACKS, readability
    for x in items:
        x["q"], x["qwhy"] = readability(x.get("v"), x.get("tags"), x.get("pack") in NONSTANDARD_PACKS)
    _PACKS.update(mtime=stamp, items=items, by_id={x["id"]: x for x in items})
    return _PACKS


_RECORD = {"stamp": None, "by": {}}
POSE_REF_MIN = 80    # a render this good (pose match %) becomes one of the pose's reference pictures


def pose_record():
    """How each pose has actually done in your renders, from the pose check saved with every image:
    {pose id: {"n": images, "avg": mean match % or None, "wrong": wrong-way count}}. Kit presets as kit-<key>."""
    d = gen.CFG["out_dir"]
    try:
        names = [n for n in os.listdir(d) if n.endswith(".json")]
        newest = max(names) if names else ""          # names start with a timestamp; scores land in the newest files
        stamp = (len(names), _mtime(d), _mtime(os.path.join(d, newest)) if newest else 0)
    except OSError:
        return {}
    if stamp == _RECORD["stamp"]:
        return _RECORD["by"]
    acc = {}
    for n in names:
        try:
            with open(os.path.join(d, n)) as f:
                m = json.load(f)
        except (OSError, ValueError):
            continue
        if "pose_score" not in m and "pose_facing" not in m:
            continue
        p = m.get("params") or {}
        pid = p.get("pose_pack_id") or (p.get("pose_key") and "kit-" + p["pose_key"])
        if not pid:
            continue
        r = acc.setdefault(pid, {"n": 0, "scores": [], "wrong": 0, "refs": []})
        r["n"] += 1
        wrong = str(m.get("pose_facing") or "").startswith("wrong")
        r["wrong"] += wrong
        if m.get("pose_score") is not None:
            r["scores"].append(m["pose_score"])
            if m["pose_score"] >= POSE_REF_MIN and not wrong and os.path.exists(os.path.join(d, n[:-5] + ".png")):
                r["refs"].append((m["pose_score"], n[:-5] + ".png"))
    removed = set(_pose_prefs().get("ref_removed", []))
    for pid, r in acc.items():
        if r["refs"] or os.path.isdir(os.path.join(REFS_DIR, pid)):
            _sync_refs(pid, r["refs"], d, removed)
    by = {pid: {"n": r["n"], "wrong": r["wrong"], "avg": round(sum(r["scores"]) / len(r["scores"])) if r["scores"] else None}
          for pid, r in acc.items()}
    for pid in (os.listdir(REFS_DIR) if os.path.isdir(REFS_DIR) else []):   # refs outlive their gallery images
        if pid not in acc and _SAFE.match(pid):
            _sync_refs(pid, [], d, removed)          # still trims to the best REF_MAX
        refs = _ref_store(pid, d)
        if refs:
            by.setdefault(pid, {"n": 0, "wrong": 0, "avg": None})["refs"] = refs
    _RECORD.update(stamp=stamp, by=by)
    return by


REFS_DIR = os.path.join(POSE_KIT, "refs")   # Pose-Kit/refs/<pose id>/<image>.png + .json: copies, safe from gallery deletes
REF_MAX = 3   # refs per pose; a better render replaces the lowest
_SAFE = re.compile(r"^[A-Za-z0-9_.-]+$")


REF_EXT = (".avif", ".png")   # refs are AVIF; .png is an older copy, converted on sight


def _save_ref(src, dst_avif):
    """AVIF, quality 88, full colour (4:4:4): about 1/9 of the PNG, visually the same (worst ~46 dB PSNR on toon art)."""
    with Image.open(src) as im:
        im.convert("RGB").save(dst_avif, "AVIF", quality=88, subsampling="4:4:4", speed=4)


def _convert_refs(folder):
    for n in os.listdir(folder):
        if n.endswith(".png") and not os.path.exists(os.path.join(folder, n[:-4] + ".avif")):
            _save_ref(os.path.join(folder, n), os.path.join(folder, n[:-4] + ".avif"))
            os.remove(os.path.join(folder, n))


def _existing_refs(folder):
    """{stem: score} of the refs already saved for a pose."""
    out = {}
    for n in (os.listdir(folder) if os.path.isdir(folder) else []):
        if n.endswith(REF_EXT):
            stem = os.path.splitext(n)[0]
            try:
                with open(os.path.join(folder, stem + ".json")) as f:
                    out[stem] = json.load(f).get("score") or 0
            except (OSError, ValueError):
                out[stem] = 0
    return out


def _drop_ref(folder, stem):
    for p in [os.path.join(folder, stem + e) for e in REF_EXT + (".json",)] + [os.path.join(folder, ".thumbs", stem + ".jpg")]:
        try:
            os.remove(p)
        except OSError:
            pass


def _sync_refs(pid, cands, gen_dir, removed):
    """Keep a pose's best REF_MAX renders (POSE_REF_MIN%+) as its refs. A new render gets in only by scoring higher
    than the lowest ref there; on a tie the ref already there stays (no churn). Pushed-out refs are deleted."""
    if not _SAFE.match(pid):
        return
    folder = os.path.join(REFS_DIR, pid)
    have = _existing_refs(folder)
    pool = [(sc, 0, stem) for stem, sc in have.items()]
    pool += [(sc, 1, name[:-4]) for sc, name in cands if name[:-4] not in have and name not in removed]
    keep = {stem for _, _, stem in sorted(pool, key=lambda t: (-t[0], t[1], t[2]))[:REF_MAX]}
    for stem in have:
        if stem not in keep:
            _drop_ref(folder, stem)
    for score, name in cands:
        stem = name[:-4]
        if stem not in keep or stem in have:
            continue
        os.makedirs(folder, exist_ok=True)
        _save_ref(os.path.join(gen_dir, name), os.path.join(folder, stem + ".avif"))
        try:
            with open(os.path.join(gen_dir, stem + ".json")) as f:
                m = json.load(f)
        except (OSError, ValueError):
            m = {}
        with open(os.path.join(folder, stem + ".json"), "w") as f:
            json.dump({"score": score, "seed": m.get("seed"), "prompt": m.get("final_prompt"), "time": m.get("time"),
                       "style": (m.get("params") or {}).get("style"), "source": name}, f)


def _ref_store(pid, gen_dir):
    """A pose's saved refs, best first: [{"file", "score", "in_gallery"}]."""
    folder = os.path.join(REFS_DIR, pid)
    if not os.path.isdir(folder):
        return []
    _convert_refs(folder)
    out = []
    for n in os.listdir(folder):
        if not n.endswith(REF_EXT):
            continue
        stem = os.path.splitext(n)[0]
        try:
            with open(os.path.join(folder, stem + ".json")) as f:
                m = json.load(f)
        except (OSError, ValueError):
            m = {}
        out.append({"file": n, "score": m.get("score"), "source": stem + ".png",
                    "in_gallery": os.path.exists(os.path.join(gen_dir, stem + ".png"))})
    return sorted(out, key=lambda r: (-(r["score"] or 0), r["file"]))


def _worked(rec):
    """A pose that has done well for you: mostly the right way round and a good average match."""
    return bool(rec) and rec["wrong"] * 2 < rec["n"] and (rec["avg"] or 0) >= 70


_kit_features = {}


def _pose_prefs():
    try:
        with open(POSE_PREFS) as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    d.setdefault("stars", []); d.setdefault("recent", []); d.setdefault("nsfw", {})
    return d


def pose_nsfw(x, prefs):
    """NSFW flag: the user's own mark wins; otherwise NSFW packs + boudoir Pose Kit presets."""
    mark = prefs.get("nsfw", {}).get(x["id"])
    return mark if mark is not None else bool(x.get("nsfw") or x["cat"] == "nsfw")


def pose_rated(items, rating, prefs):
    """rating: SFW = hide NSFW, NSFW = only NSFW, anything else = all."""
    if rating == "SFW":
        return [x for x in items if not pose_nsfw(x, prefs)]
    if rating == "NSFW":
        return [x for x in items if pose_nsfw(x, prefs)]
    return list(items)


def _save_pose_prefs(d):
    with open(POSE_PREFS, "w") as f:
        json.dump(d, f)


def pack_pose_path(pid):
    x = pose_packs()["by_id"].get(pid)
    if not x:
        return None
    return x["path"] if x.get("abs") else os.path.join(MINE_DIR if x["cat"] == "mine" else PACKS_DIR, x["path"])


@functools.lru_cache(maxsize=64)
def _skel_vector(path):
    from lib_pl.pose_features import keypoints, vector
    kp, _, _ = keypoints(path)
    return vector(kp)


@functools.lru_cache(maxsize=64)
def _skel_tags(path):
    from lib_pl.pose_features import keypoints, tags_for
    kp, people, size = keypoints(path)
    return tuple(tags_for(kp, people, size))


def pose_view(params, skel=None):
    """View tags of the job's pose: a pose pack's tags, or for a Pose Kit preset its hand-written tags plus what its
    skeleton shows. Used to expect a facing and to make sure back views say so in the prompt."""
    p = params or {}
    if p.get("pose_pack_id"):
        return list((pose_packs()["by_id"].get(p["pose_pack_id"]) or {}).get("tags") or [])
    tags = []
    if p.get("pose_key"):
        pre = next((v for v in pose_presets().values() if v["key"] == p["pose_key"]), None)
        if pre:
            tags = [t.strip() for t in pre["tags"].split(",")]
            if "from side" in tags or "three-quarter view" in tags:
                return tags
    if skel and not any(t in tags for t in ("from behind", "front view")):
        tags += list(_skel_tags(skel))
    return tags


def pose_score(skel, img, params=None):
    """Pose match for a generated image: Forge's DWPose reads the body, compared joint by joint with the skeleton.
    With several people in the image, the best-matching one counts. A body facing the other way from the skeleton
    (front instead of back or the reverse) is capped at 30% and marked, since joint positions alone can't see it."""
    import base64
    from lib_pl.pose_features import NONSTANDARD_PACKS, expected_facing, facing, from_openpose_json, match, vector
    pid = (params or {}).get("pose_pack_id")
    x = pose_packs()["by_id"].get(pid) if pid else None
    target = (x or {}).get("v")
    if target is None:
        target = _skel_vector(skel)
    if target is None:
        return None
    with open(img, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    pose = {}
    for module in ("dw_openpose_full", "openpose"):   # DWPose's person finder misses some cartoon bodies
        r = gen._call("/controlnet/detect", {"controlnet_module": module, "controlnet_input_images": [b64],
                                             "controlnet_processor_res": 512}, timeout=300)
        pose = (r.get("poses") or [{}])[0]
        if pose.get("people"):
            break
    w, h = pose.get("canvas_width"), pose.get("canvas_height")
    if not (w and h):
        with Image.open(img) as im:
            w, h = im.size
    people = [vector(from_openpose_json(person, w, h)) for person in pose.get("people") or []]
    if not people:
        # stylized bodies (very curvy toon proportions, low contrast) can defeat both readers: that's "can't check",
        # not a failed pose, so no 0% and no retry
        return {"score": None, "facing": "unchecked: no body found by the pose reader"}
    scored = sorted(((match(target, v), v) for v in people), key=lambda t: -1 if t[0] is None else t[0], reverse=True)
    score, v = scored[0]   # None: the skeleton itself was too hard to read to judge joint by joint
    want = None if (x or {}).get("pack") in NONSTANDARD_PACKS else expected_facing(pose_view(params, skel))
    got = facing(v)
    view = pose_view(params, skel)
    if want == "back" and "looking back" in view:
        want = None   # a face turned over the shoulder makes the reader call the body front-facing: can't judge
    if want and got and want != got:
        return {"score": None if score is None else min(score, 30), "facing": f"wrong: {got} instead of {want}"}
    return {"score": score, "facing": "ok" if want and got else None}


def pack_depth_path(pid):
    """Depth map that came with a skeleton: packs ship X_bone_structure.png + X_depth.png or N-pose[-B].png +
    N-depth[-B].png; "From image" poses get mine-*_depth.png. None when there is none."""
    skel = pack_pose_path(pid)
    if not skel:
        return None
    d, f = os.path.split(skel)
    stem = os.path.splitext(f)[0]
    for cand in (stem + "_depth", stem.replace("_bone_structure", "_depth"), re.sub(r"-pose(?=-|$)", "-depth", stem)):
        p = os.path.join(d, cand + ".png")
        if cand != stem and os.path.exists(p):
            return p
    return None


def _pub(x, prefs):
    from lib_pl.pose_features import prompt_tags
    return {"id": x["id"], "label": x["label"], "pack": x["pack"], "w": x["w"], "h": x["h"], "cat": x["cat"],
            "depth": bool(pack_depth_path(x["id"])), "q": x.get("q"), "qwhy": x.get("qwhy"),
            "rec": pose_record().get(x["id"]),
            "tags": x.get("tags", []), "star": x["id"] in prefs["stars"], "nsfw": pose_nsfw(x, prefs),
            "ptags": x.get("kit_tags") or prompt_tags(x.get("tags", []))}


# prompt words -> pose tags, for "poses that match this prompt"
_PROMPT_TO_POSE = [("all fours", "all fours"), ("on all fours", "all fours"), ("kneel", "kneeling"), ("squat", "squatting"),
                   ("crouch", "squatting"), ("lying", "lying"), ("on back", "lying"), ("on stomach", "lying"),
                   ("sitting", "sitting"), ("seated", "sitting"), ("standing", "standing"), ("arms up", "arms up"),
                   ("arms raised", "arms up"), ("arm up", "arm up"), ("hands on hips", "hands on hips"),
                   ("hand on hip", "hand on hip"), ("crossed arms", "crossed arms"), ("arms crossed", "crossed arms"),
                   ("outstretched", "arms out"), ("from behind", "from behind"), ("looking back", "from behind"),
                   ("from side", "from side"), ("crossed legs", "crossed legs"), ("legs crossed", "crossed legs"),
                   ("legs apart", "wide stance"), ("leg up", "leg up"), ("dynamic pose", "dynamic"), ("action", "dynamic"),
                   ("full body", "full body"), ("cowboy shot", "cowboy shot"), ("upper body", "upper body")]


@app.get("/api/posepacks/suggest/{rid}")
def posepack_suggest(rid: int, rating: str = "SFW", limit: int = 12):
    """Poses whose tags match the pose words in a library prompt (drops the rarest tag until enough match)."""
    r = library().by_id.get(rid)
    if r is None:
        raise HTTPException(404, "Not in library")
    text = (r.get("prompt") or "").lower().replace("_", " ")
    want = []
    for word, tag in _PROMPT_TO_POSE:
        if word in text and tag not in want:
            want.append(tag)
    if "arms up" in want and "arm up" in want:
        want.remove("arm up")
    prefs = _pose_prefs()
    P = pose_rated(pose_packs()["items"], rating, prefs)
    freq = {t: sum(1 for x in P if t in x.get("tags", [])) for t in want}
    use = sorted(want, key=lambda t: -freq[t])
    rows = []
    while use:
        rows = [x for x in P if all(t in x.get("tags", []) for t in use)]
        if len(rows) >= 6:
            break
        use = use[:-1]
    return {"wanted": want, "used": use, "items": [_pub(x, prefs) for x in rows[:max(1, min(limit, 48))]]}


POSE_FILTERS = [  # the pose browser's filter dropdowns: one pick per group, groups combine
    ("Body", ["standing", "sitting", "kneeling", "squatting", "lying", "all fours", "leaning"]),
    ("Facing", ["front view", "from behind", "looking back", "from side"]),
    ("Framing", ["full body", "cowboy shot", "upper body", "close-up"]),
    ("Arms", ["arms up", "arm up", "hands on hips", "hand on hip", "hand on head", "hand on face", "arms out", "crossed arms"]),
    ("Legs", ["leg up", "crossed legs", "wide stance"]),
    ("Other", ["dynamic", "group"]),
]


def _has_depth(x):
    if "has_depth" not in x:
        x["has_depth"] = bool(pack_depth_path(x["id"]))
    return x["has_depth"]


def _ref_path(pid, file):
    if not (_SAFE.match(pid) and _SAFE.match(file) and file.endswith(REF_EXT)):
        raise HTTPException(400, "Bad name")
    p = os.path.join(REFS_DIR, pid, file)
    if not os.path.exists(p):
        raise HTTPException(404, "Not found")
    return p


@app.get("/api/posepacks/ref/{pid}/{file}")
def posepack_ref(pid: str, file: str):
    p = _ref_path(pid, file)
    return FileResponse(p, media_type="image/avif" if p.endswith(".avif") else "image/png", headers={"Cache-Control": "max-age=604800"})


@app.get("/api/posepacks/refthumb/{pid}/{file}")
def posepack_refthumb(pid: str, file: str):
    src = _ref_path(pid, file)
    out = os.path.join(REFS_DIR, pid, ".thumbs", os.path.splitext(file)[0] + ".jpg")
    if not os.path.exists(out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with Image.open(src) as im:
            im = im.convert("RGB"); im.thumbnail((320, 480)); im.save(out, quality=82)
    return FileResponse(out, headers={"Cache-Control": "max-age=604800"})


@app.post("/api/posepacks/ref/remove")
def posepack_ref_remove(pid: str = Body(...), file: str = Body(...)):
    """Take a picture off a pose's refs for good (it won't be re-added, even if it's still in the gallery)."""
    src = _ref_path(pid, file)
    stem = os.path.splitext(file)[0]
    for p in (src, os.path.join(REFS_DIR, pid, stem + ".json"), os.path.join(REFS_DIR, pid, ".thumbs", stem + ".jpg")):
        try:
            os.remove(p)
        except OSError:
            pass
    prefs = _pose_prefs()
    prefs["ref_removed"] = sorted(set(prefs.get("ref_removed", [])) | {stem + ".png"})   # keyed by the gallery name
    _save_pose_prefs(prefs)
    _RECORD["stamp"] = None
    return {"ok": True, "refs": _ref_store(pid, gen.CFG["out_dir"])}


@app.get("/api/posepacks/item/{pid}")
def posepack_item(pid: str):
    """One pose as the browser shows it (Generate restores the picked pose after a restart)."""
    x = pose_packs()["by_id"].get(pid)
    if not x:
        raise HTTPException(404, "Pose not found")
    return _pub(x, _pose_prefs())


@app.get("/api/posepacks")
def posepacks(cat: str = "", pack: str = "", q: str = "", tags: str = "", page: int = 0, per: int = 60, rating: str = "SFW",
              clear: bool = False, depth: bool = False):
    """cat: fashion|dynamic|nsfw|kit|mine|starred|recent|worked. tags: comma list, all must match.
    clear: hide skeletons Spellbook can't read well. depth: only poses with a depth map.
    filters: each dropdown group with its options and how many poses each would give (with the other picks kept)."""
    P = pose_packs()["items"]
    prefs = _pose_prefs()
    allowed = pose_rated(P, rating, prefs)
    packs = {}
    for x in allowed:
        packs.setdefault(x["pack"], {"name": x["pack"], "cat": x["cat"], "count": 0})["count"] += 1
    if cat == "starred":
        rows = [x for x in allowed if x["id"] in prefs["stars"]]
    elif cat == "recent":
        order = {pid: i for i, pid in enumerate(prefs["recent"])}
        rows = sorted((x for x in allowed if x["id"] in order), key=lambda x: order[x["id"]])
    elif cat == "refs":
        rec = pose_record()
        rows = [x for x in allowed if (rec.get(x["id"]) or {}).get("refs")]
    elif cat == "worked":
        rec = pose_record()
        rows = sorted((x for x in allowed if _worked(rec.get(x["id"]))), key=lambda x: -(rec[x["id"]]["avg"] or 0))
    else:
        rows = [x for x in allowed if not cat or x["cat"] == cat]
    want = [t.strip() for t in tags.split(",") if t.strip()]
    ql = q.lower().strip()
    base = [x for x in rows if (not clear or x.get("q") != "unclear") and (not pack or x["pack"] == pack)
            and (not depth or _has_depth(x))
            and (not ql or ql in x["label"].lower() or ql in x["pack"].lower() or any(ql in t for t in x.get("tags", [])))]
    filters = []
    for name, opts_ in POSE_FILTERS:
        others = [t for t in want if t not in opts_]
        pool = [x for x in base if all(t in x.get("tags", []) for t in others)]
        filters.append({"name": name, "selected": next((t for t in want if t in opts_), ""),
                        "options": [[o, sum(1 for x in pool if o in x.get("tags", []))] for o in opts_]})
    rows = [x for x in base if all(t in x.get("tags", []) for t in want)]
    counts = {}
    for x in rows:
        for t in x.get("tags", []):
            counts[t] = counts.get(t, 0) + 1
    per = max(12, min(per, 200))
    return {"packs": sorted(packs.values(), key=lambda p: (p["cat"], -p["count"])), "total": len(rows),
            "tag_counts": sorted(counts.items(), key=lambda kv: -kv[1]), "filters": filters,
            "items": [_pub(x, prefs) for x in rows[page * per:(page + 1) * per]],
            "page": page, "pages": max(1, -(-len(rows) // per))}


@app.get("/api/posepacks/similar/{pid}")
def posepack_similar(pid: str, rating: str = "SFW", limit: int = 60):
    from lib_pl.pose_features import similar
    P = pose_packs()
    x = P["by_id"].get(pid)
    if not x or not x.get("v"):
        raise HTTPException(404, "That pose has no readable joints, so it can't be matched.")
    prefs = _pose_prefs()
    pool = [(y["id"], y["v"]) for y in pose_rated(P["items"], rating, prefs) if y["id"] != pid and y.get("v")]
    return {"of": _pub(x, prefs), "items": [_pub(P["by_id"][i], prefs) for i, _ in similar(x["v"], pool, limit=max(6, min(limit, 120)))]}


@app.post("/api/posepacks/star")
def posepack_star(id: str = Body(...), on: bool = Body(True)):
    d = _pose_prefs()
    d["stars"] = [s_ for s_ in d["stars"] if s_ != id] + ([id] if on else [])
    _save_pose_prefs(d)
    return {"ok": True, "star": on}


@app.post("/api/posepacks/nsfw")
def posepack_nsfw(id: str = Body(...), on: bool = Body(True)):
    """Mark one pose NSFW (or safe). Stored as an override, so it also corrects pack defaults."""
    if id not in pose_packs()["by_id"]:
        raise HTTPException(404, "Unknown pose")
    d = _pose_prefs()
    d["nsfw"][id] = bool(on)
    _save_pose_prefs(d)
    return {"ok": True, "nsfw": bool(on)}


@app.post("/api/posepacks/used")
def posepack_used(id: str = Body(..., embed=True)):
    d = _pose_prefs()
    d["recent"] = [id] + [r for r in d["recent"] if r != id][:39]
    _save_pose_prefs(d)
    return {"ok": True}


@app.post("/api/pose/detect")
def pose_detect(gen_name: str = Body(None), input_name: str = Body(None), hist_id: str = Body(None)):
    """Extract a skeleton from one of your images with Forge's DWPose detector; it joins "From your images"."""
    import base64
    from lib_pl.pose_features import from_openpose_json, tags_for, vector
    if gen_name:
        src = gen._path(gen_name)
    elif input_name:
        src = gen._input_path(input_name)
    elif hist_id:
        src = _history_path(hist_id, ".jpg")
    else:
        raise HTTPException(400, "Pick an image first.")
    with open(src, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    try:
        r = gen._call("/controlnet/detect", {"controlnet_module": "dw_openpose_full", "controlnet_input_images": [b64],
                                             "controlnet_processor_res": 768}, timeout=300)
    except Exception as e:
        raise HTTPException(503, f"{gen._offline(e)} Pose detection runs inside Forge.")
    if not r.get("images"):
        raise HTTPException(500, "Forge returned no skeleton. Try an image where the whole figure is visible.")
    os.makedirs(MINE_DIR, exist_ok=True)
    pid = "mine-" + time.strftime("%Y%m%d%H%M%S")
    png = base64.b64decode(r["images"][0].split(",", 1)[-1])
    with open(os.path.join(MINE_DIR, pid + ".png"), "wb") as f:
        f.write(png)
    try:  # depth of the same image, so the pose can also lock body shape and which limb is in front
        d = gen._call("/controlnet/detect", {"controlnet_module": "depth_anything_v2", "controlnet_input_images": [b64],
                                             "controlnet_processor_res": 768}, timeout=300)
        if d.get("images"):
            with open(os.path.join(MINE_DIR, pid + "_depth.png"), "wb") as f:
                f.write(base64.b64decode(d["images"][0].split(",", 1)[-1]))
    except Exception:
        pass
    with Image.open(io.BytesIO(png)) as im:
        w, h = im.size
        t = im.convert("RGB"); t.thumbnail((200, 300))
        os.makedirs(os.path.join(PACKS_DIR, "_thumbs"), exist_ok=True)
        t.save(os.path.join(PACKS_DIR, "_thumbs", pid + ".jpg"), quality=80)
    people = ((r.get("poses") or [{}])[0].get("people") or [])
    kp = from_openpose_json(people[0], w, h) if people else None
    item = {"id": pid, "label": os.path.basename(src), "path": pid + ".png", "w": w, "h": h,
            "tags": tags_for(kp, max(1, len(people)), (w, h)), "v": vector(kp)}
    idx_path = os.path.join(MINE_DIR, "index.json")
    try:
        with open(idx_path) as f:
            mine = json.load(f)
    except (OSError, ValueError):
        mine = []
    mine.insert(0, item)
    with open(idx_path, "w") as f:
        json.dump(mine, f)
    P = pose_packs()
    return {"pose": _pub(P["by_id"][pid], _pose_prefs()), "people": len(people)}


@app.get("/api/posepacks/thumb/{pid}")
def posepack_thumb(pid: str):
    if pid.startswith("kit-"):
        p = pack_pose_path(pid)
        if not p:
            raise HTTPException(404)
        return FileResponse(p, headers={"Cache-Control": "max-age=86400"})
    if not re.fullmatch(r"[0-9a-f]{12}|mine-\d{14}", pid):
        raise HTTPException(400)
    p = os.path.join(PACKS_DIR, "_thumbs", pid + ".jpg")
    if not os.path.exists(p):
        raise HTTPException(404)
    return FileResponse(p, headers={"Cache-Control": "max-age=604800"})


@app.get("/api/posepacks/image/{pid}")
def posepack_image(pid: str):
    p = pack_pose_path(pid)
    if not p or not os.path.exists(p):
        raise HTTPException(404)
    return FileResponse(p, headers={"Cache-Control": "max-age=604800"})


@app.get("/api/pose/skeleton/{key}")
def pose_skeleton(key: str):
    p = next((v["skeleton"] for v in _get_poses().values() if v["key"] == key and v["skeleton"]), None)
    if not p:
        raise HTTPException(404)
    return FileResponse(p, headers={"Cache-Control": "max-age=86400"})


@app.post("/api/krita/prompt")
def krita_prompt(prompt: str = Body(...), negative: str = Body(""), style: str = Body("")):
    return _bridge("/prompt", {"prompt": prompt, "negative": negative, "style": style})


@app.post("/api/krita/pose")
def krita_pose(key: str = Body(None), pack_id: str = Body(None)):
    if pack_id:
        p = pack_pose_path(pack_id)
        if not p:
            raise HTTPException(404, "No such pose")
        x = pose_packs()["by_id"][pack_id]
        return _bridge("/pose", {"path": p, "name": f"{x['pack'][:24]} · {x['label'][:24]}"}, timeout=15)
    v = next((v for k, v in _get_poses().items() if v["key"] == key), None)
    if not v or not v["skeleton"]:
        raise HTTPException(404, "No skeleton for that pose")
    label = next(k for k, x in _get_poses().items() if x["key"] == key)
    return _bridge("/pose", {"path": v["skeleton"], "name": label}, timeout=15)


@app.get("/api/krita/status")
def krita_status():
    try:
        resp = httpx.get(f"{KRITA_BRIDGE}/ping", timeout=httpx.Timeout(1.5, connect=1.0))
        d = resp.json()
        return {"online": True, "document": d.get("document", False), "doc_name": d.get("doc_name"), "size": d.get("size")}
    except Exception:
        return {"online": False, "document": False}


@app.post("/api/clean")
def do_clean(text: str = Body(...), negative: bool = Body(False), framing: bool = Body(True), auto: bool = Body(False),
             pose: str = Body("")):
    """auto = Generate's automatic pass: only duplicates and conflicting tags come out (no typo fixes);
    conflicts = a second framing tag, posture, view direction or camera height that contradicts an earlier one.
    pose = the picked pose's tags: tags that fight the pose come out first (the pose wins, not the earlier tag)."""
    out, notes = clean(text or "", positive=not negative, framing=framing, typos=not auto)
    if auto and not negative:
        from lib_pl.poses import pose_wins, resolve
        if pose:
            out, fought = pose_wins(out, pose)
            notes += [f"dropped {t} (fights the pose)" for t in fought]
        out, gone = resolve(out)
        notes += [f"dropped {t} (conflict)" for t in gone]
    return {"text": out, "notes": notes}


@app.post("/api/interrogate")
def do_interrogate(image: UploadFile = File(...), preset: str = Form(...), engine: str = Form(TAGS_ONLY)):
    presets = load_presets(PRESETS_PATH)
    if preset not in presets:
        raise HTTPException(400, f"Unknown preset: {preset}")
    img = Image.open(io.BytesIO(image.file.read()))
    writers = {LOCAL: OllamaWriter(S["ollama_url"], S["ollama_model"]),
               CLAUDE: ClaudeWriter(_claude_key()[0], S["claude_model"])}
    tt = _ThresholdTagger(tagger())
    try:
        r = interrogate(img, presets[preset], engine, tt, writers)
    except Exception as e:
        raise HTTPException(500, f"{e.__class__.__name__}: {e}")
    kp, kn, style, notes = to_krita(r.character or r.prompt, "", "Illustrious")
    res = {"prompt": r.prompt, "negative": r.negative, "settings": r.settings, "notes": r.notes.splitlines(),
           "character": r.character, "engine": r.engine_used, "krita_style": style.split(" (needs")[0],
           "preset": preset, "tags": group_tags(tt.raw or {}), "rating": (tt.raw or {}).get("rating", {}),
           "thresholds": {"general": S["general_threshold"], "character": S["character_threshold"]}}
    return _history_save(img, res)


@app.get("/api/interrogate/history")
def interrogate_history():
    if not os.path.isdir(HISTORY_DIR):
        return []
    out = []
    for n in sorted(os.listdir(HISTORY_DIR), reverse=True):
        if n.endswith(".json"):
            try:
                with open(os.path.join(HISTORY_DIR, n)) as f:
                    d = json.load(f)
                out.append({"id": d["id"], "preset": d.get("preset", ""), "engine": d.get("engine", ""), "time": d.get("time")})
            except (OSError, ValueError, KeyError):
                pass
    return out


@app.get("/api/interrogate/result/{hid}")
def interrogate_result(hid: str):
    with open(_history_path(hid, ".json")) as f:
        return json.load(f)


@app.get("/api/interrogate/image/{hid}")
def interrogate_image(hid: str):
    return FileResponse(_history_path(hid, ".jpg"), headers={"Cache-Control": "max-age=604800"})


@app.post("/api/interrogate/delete")
def interrogate_delete(id: str = Body(..., embed=True)):
    for ext in (".jpg", ".json"):
        try:
            os.remove(_history_path(id, ext))
        except HTTPException:
            pass
    return {"ok": True}


@app.post("/api/similar")
def find_similar(tags: list = Body(...), rating: str = Body("SFW"), limit: int = Body(12)):
    """tags: [{tag, score, group}] — the chips the user kept."""
    probes = [(t["tag"], float(t.get("score", 0.5)), t.get("group") == "Character") for t in tags if t.get("tag")]
    probes.sort(key=lambda x: (not x[2], -x[1]))
    rows = similar(library().rows, probes, limit=max(1, min(int(limit), 48)), safe_only=rating == "SFW", safe_values=SAFE)
    names = [t for t, _, _ in probes]
    return {"items": [{"id": r["id"], "base": r.get("base") or "?", "react": r.get("react") or 0} for r in rows],
            "loras": lora_suggestions(names, S["lora_dir"])}


def _forge_url():
    return (S.get("forge_url") or "http://127.0.0.1:7860").rstrip("/")


@app.post("/api/krita/open")
def krita_open(gen_name: str = Body(..., embed=True)):
    p = gen._path(gen_name)
    r = _bridge("/open", {"path": p}, timeout=15)
    if r.get("error") == "unknown endpoint":
        r["error"] = "Krita's AI Prompt Bridge is out of date. Restart Krita to load the new version."
    if r.get("ok"):
        meta_path = p[:-4] + ".json"
        if os.path.exists(meta_path):
            try:
                with open(meta_path) as f:
                    meta = json.load(f)
                meta["krita"] = {
                    "opened_at": time.time(),
                    "document": r.get("name"),
                    "size": r.get("size"),
                    "color_depth": r.get("color_depth"),
                    "resolution": r.get("resolution"),
                }
                with open(meta_path, "w") as f:
                    json.dump(meta, f)
            except Exception:
                pass
    return r


@app.post("/api/krita/image")
def krita_image(id: str = Body(None), modes: list = Body(["reference"]), gen_name: str = Body(None)):
    allowed = {"reference", "style", "composition", "face", "pose", "depth", "line_art", "canny_edge", "layer"}
    modes = [m for m in modes if m in allowed] or ["layer"]
    path = gen._path(gen_name) if gen_name else _history_path(id, ".jpg")
    r = _bridge("/image", {"path": path, "modes": [m for m in modes if m != "layer"],
                           "name": f"Ref · {gen_name or id}"}, timeout=12)
    if r.get("error") == "unknown endpoint":
        r["error"] = "Krita's AI Prompt Bridge is out of date. Restart Krita to load the new version."
    if r.get("ok") and gen_name:
        meta_path = path[:-4] + ".json"
        if os.path.exists(meta_path):
            try:
                with open(meta_path) as f:
                    meta = json.load(f)
                km = meta.get("krita") or {}
                km["sent_layers"] = list(set(km.get("sent_layers", []) + [r.get("layer")]))
                km["modes"] = list(set(km.get("modes", []) + (r.get("modes") or [])))
                meta["krita"] = km
                with open(meta_path, "w") as f:
                    json.dump(meta, f)
            except Exception:
                pass
    return r


@app.post("/api/open")
def open_external(url: str = Body(..., embed=True)):
    if not url.startswith("https://civitai.com/"):
        raise HTTPException(400, "Only Civitai links open from here.")
    webbrowser.open(url)
    return {"ok": True}


@app.post("/api/seed")
def new_seed():
    return {"seed": random.randint(1, 10**9)}


import forgectl  # noqa: E402

forgectl.configure(os.path.expanduser(S.get("forge_dir") or FORGE), _forge_url(), os.path.join(APP_DIR, "forge.log"))
app.include_router(forgectl.router)

import gen  # noqa: E402

gen.configure(_forge_url(), os.path.expanduser(S.get("gen_dir") or os.path.join(APP_DIR, "generations")), S["lora_dir"])
gen.CFG["export_dir"] = os.path.expanduser(S.get("export_dir") or os.path.join(APP_DIR, "exports"))
gen.CFG["pose_pack_path"] = pack_pose_path
gen.CFG["pose_score"] = pose_score
gen.CFG["pose_depth_path"] = pack_depth_path
gen.CFG["pose_view"] = pose_view
app.include_router(gen.router)


@app.get("/api/record/{rid}/gen")
def record_gen(rid: int):
    """Library record -> Generate tab params (prompt, negative, sampler, scheduler, steps, cfg, size, clip skip)."""
    r = library().by_id.get(rid)
    if r is None:
        raise HTTPException(404, "Not in library")
    prompt, neg, st = record_settings(r)
    return {"prompt": prompt, "negative": neg, "sampler": st["sampler"], "scheduler": st.get("scheduler") or "Automatic",
            "steps": st["steps"], "cfg": st["cfg"], "width": st["width"], "height": st["height"],
            "clip_skip": st.get("clip_skip") or 0, "distilled_cfg": st.get("distilled_cfg"), "base": r.get("base") or ""}


# ------------------------------------------------------------------ settings: what's connected, where files go
CLAUDE_KEY_SERVICE = "Spellbook Claude API key"
FOLDERS = [  # id, label, settings key (None = fixed), what it holds
    ("gen_dir", "Generated images", "gen_dir", "Every image you generate, with a .json of its settings beside it. The gallery shows this folder."),
    ("export_dir", "Exports", "export_dir", "Where Export in the gallery copies images, with their prompts as .txt."),
    ("library_path", "Prompt library", "library_path", "Folder holding your prompt library (all-prompts.json sidecar)."),
    ("lora_dir", "LoRAs", "lora_dir", "Your installed LoRAs. Used for the LoRA picker, Runnable and missing-model checks."),
    ("forge_dir", "Forge", "forge_dir", "Stable Diffusion Forge. The Forge switch starts webui.sh from here."),
    ("pose_kit", "Pose Kit", None, "Pose presets, skeleton packs and depth maps."),
    ("app_dir", "App data", None, "Collections, settings, thumbnails, logs."),
]


def _claude_key():
    """(key, where it came from): environment variable, then Keychain, then an old plain-text settings value."""
    from lib_pl import keychain
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"], "environment variable"
    k = keychain.get(CLAUDE_KEY_SERVICE)
    if k:
        return k, "Keychain"
    if S.get("anthropic_key"):
        return S["anthropic_key"], "settings file"
    return "", ""


def _folder_path(fid):
    return {"gen_dir": gen.CFG["out_dir"], "export_dir": gen.CFG["export_dir"],
            "library_path": os.path.expanduser(S["library_path"]), "lora_dir": os.path.expanduser(S["lora_dir"]),
            "forge_dir": forgectl.CFG["forge_dir"],
            "pose_kit": POSE_KIT, "app_dir": APP_DIR}[fid]


def _ping(url, timeout=1.5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.load(r)
    except Exception:
        return None


def _version():
    import subprocess
    try:
        return subprocess.run(["git", "describe", "--tags", "--always"], cwd=EXT_DIR, capture_output=True, text=True,
                              timeout=3).stdout.strip()
    except Exception:
        return ""


@app.get("/api/settings")
def settings_get():
    folders = []
    for fid, label, key, note in FOLDERS:
        p = _folder_path(fid)
        folders.append({"id": fid, "label": label, "path": p, "editable": bool(key), "exists": os.path.isdir(p), "note": note})
    om = _ping(S["ollama_url"].rstrip("/") + "/api/tags")
    key, src = _claude_key()
    return {
        "folders": folders,
        "connections": {
            "forge": {"url": _forge_url(), "online": _ping(_forge_url() + "/sdapi/v1/progress", 2) is not None},
            "krita": {"url": KRITA_BRIDGE, "online": krita_status()["online"]},
            "ollama": {"url": S["ollama_url"], "model": S["ollama_model"], "online": om is not None,
                       "models": [m.get("name") for m in (om or {}).get("models", [])]},
            "claude": {"model": S["claude_model"], "key_set": bool(key), "key_source": src,
                       "key_hint": (key[:7] + "…" + key[-4:]) if len(key) > 16 else ""},
        },
        "interrogate": {"general_threshold": S["general_threshold"], "character_threshold": S["character_threshold"]},
        "app": {"version": _version(), "data_dir": APP_DIR},
    }


def _save_settings(changes):
    try:
        with open(SETTINGS_PATH) as f:
            saved = json.load(f)
    except (OSError, ValueError):
        saved = {}
    saved.update(changes)
    with open(SETTINGS_PATH, "w") as f:
        json.dump(saved, f, indent=1)
    S.update(changes)


def _move_outputs(old, new):
    """Move generated images (+ .json, inputs/) from the old folder to the new one. Never overwrites."""
    import shutil
    moved = 0
    for n in os.listdir(old):
        src, dst = os.path.join(old, n), os.path.join(new, n)
        if os.path.exists(dst):
            if os.path.isdir(src) and os.path.isdir(dst):
                moved += _move_outputs(src, dst)
            continue
        if n.endswith((".png", ".json")) or (n == "inputs" and os.path.isdir(src)):
            shutil.move(src, dst)
            moved += 1
    return moved


@app.post("/api/settings")
def settings_save(changes: dict = Body(...), move_outputs: bool = Body(False)):
    """Save settings and apply them right away (no restart). Folder values are checked before anything is saved."""
    ok_keys = {"gen_dir", "export_dir", "library_path", "lora_dir", "forge_dir", "forge_url", "ollama_url", "ollama_model",
               "claude_model", "general_threshold", "character_threshold"}
    bad = sorted(set(changes) - ok_keys)
    if bad:
        raise HTTPException(400, f"Unknown setting: {', '.join(bad)}")
    clean_ = {}
    for k, v in changes.items():
        if k.endswith(("_dir", "_path")):
            p = os.path.abspath(os.path.expanduser(str(v).strip()))
            if k in ("gen_dir", "export_dir"):
                p = _beta_output_path(p)
                try:
                    os.makedirs(p, exist_ok=True)
                except OSError as e:
                    raise HTTPException(400, f"Can't use {p}: {e.strerror}")
            elif not os.path.isdir(p):
                raise HTTPException(400, f"Folder not found: {p}")
            if k == "forge_dir" and not os.path.exists(os.path.join(p, "webui.sh")):
                raise HTTPException(400, f"No webui.sh in {p}. Pick the Forge folder itself.")
            clean_[k] = p
        elif k.endswith("threshold"):
            clean_[k] = max(0.05, min(0.95, float(v)))
        else:
            clean_[k] = str(v).strip()
    moved = 0
    if "gen_dir" in clean_ and clean_["gen_dir"] != gen.CFG["out_dir"]:
        old = gen.CFG["out_dir"]
        if gen._worker.get("thread"):
            raise HTTPException(409, "Images are generating. Change the folder when the queue is done.")
        if move_outputs and os.path.isdir(old):
            moved = _move_outputs(old, clean_["gen_dir"])
        gen.CFG["out_dir"] = clean_["gen_dir"]
    if "export_dir" in clean_:
        gen.CFG["export_dir"] = clean_["export_dir"]
    if "lora_dir" in clean_:
        gen.CFG["lora_dir"] = clean_["lora_dir"]
    if "forge_dir" in clean_:
        forgectl.CFG["forge_dir"] = clean_["forge_dir"]
    if "forge_url" in clean_:
        forgectl.CFG["forge_url"] = gen.CFG["forge_url"] = clean_["forge_url"].rstrip("/")
    _save_settings(clean_)
    if "library_path" in clean_:
        _state["lib"] = None   # reloads from the new folder on next use
    return {"ok": True, "moved": moved, "settings": settings_get()}


@app.post("/api/settings/choose-folder")
def settings_choose_folder(current: str = Body(""), prompt: str = Body("Choose a folder")):
    """Native macOS folder picker (AppleScript). Returns {"path"} or {"cancelled": true}."""
    import subprocess
    start = current if os.path.isdir(current) else os.path.expanduser("~")
    script = (f'set p to POSIX path of (choose folder with prompt {json.dumps(prompt)} '
              f'default location (POSIX file {json.dumps(start)}))\nreturn p')
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        return {"cancelled": True}
    return {"path": r.stdout.strip().rstrip("/") or "/"}


@app.post("/api/settings/reveal")
def settings_reveal(path: str = Body(..., embed=True)):
    import subprocess
    p = os.path.expanduser(path)
    if not os.path.exists(p):
        raise HTTPException(404, "That folder doesn't exist yet.")
    subprocess.run(["open", p], check=False)
    return {"ok": True}


@app.post("/api/settings/claude-key")
def settings_claude_key(key: str = Body("", embed=True)):
    """Save the Claude API key to the Keychain (empty removes it). A key in the old settings file is dropped."""
    from lib_pl import keychain
    key = key.strip()
    if key and not key.startswith("sk-ant-"):
        raise HTTPException(400, "That doesn't look like a Claude API key (they start with sk-ant-).")
    if not keychain.set(CLAUDE_KEY_SERVICE, key):
        raise HTTPException(500, "Couldn't save to the Keychain.")
    if "anthropic_key" in S:
        try:
            with open(SETTINGS_PATH) as f:
                saved = json.load(f)
            saved.pop("anthropic_key", None)
            with open(SETTINGS_PATH, "w") as f:
                json.dump(saved, f, indent=1)
        except (OSError, ValueError):
            pass
        S.pop("anthropic_key", None)
    return {"ok": True, "settings": settings_get()}


@app.post("/api/settings/test")
def settings_test(what: str = Body(..., embed=True)):
    """Check one connection and say plainly what's wrong."""
    if what == "forge":
        ok = _ping(_forge_url() + "/sdapi/v1/progress", 3) is not None
        return {"ok": ok, "message": "Forge is answering." if ok else f"No answer from Forge at {_forge_url()}. Start it with the Forge switch."}
    if what == "krita":
        ok = krita_status()["online"]
        return {"ok": ok, "message": "Krita bridge is connected." if ok else "Krita isn't answering. Open Krita and enable the AI Prompt Bridge add-on."}
    if what == "ollama":
        om = _ping(S["ollama_url"].rstrip("/") + "/api/tags", 3)
        if om is None:
            return {"ok": False, "message": f"Ollama isn't running at {S['ollama_url']}."}
        names = [m.get("name") for m in om.get("models", [])]
        ok = S["ollama_model"] in names
        return {"ok": ok, "message": f"Ollama is running and has {S['ollama_model']}." if ok else
                f"Ollama is running but doesn't have {S['ollama_model']}. Run: ollama pull {S['ollama_model']}"}
    if what == "claude":
        key, _ = _claude_key()
        if not key:
            return {"ok": False, "message": "No Claude API key yet."}
        req = urllib.request.Request("https://api.anthropic.com/v1/models", headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
        try:
            with urllib.request.urlopen(req, timeout=8):
                return {"ok": True, "message": "Claude key works."}
        except urllib.error.HTTPError as e:
            return {"ok": False, "message": "Claude rejected the key." if e.code in (401, 403) else f"Claude returned {e.code}."}
        except Exception:
            return {"ok": False, "message": "Couldn't reach Claude. Check your internet connection."}
    raise HTTPException(400, "Unknown connection")


# ---- the Mac window's title bar takes the theme's background (set by the page whenever the theme changes)
_WINDOW = {"win": None, "geo": None}
_HEX = re.compile(r"#[0-9a-fA-F]{6}")


def _paint_titlebar(color):
    """Transparent title bar over a window background in the theme color; light title text and window buttons.
    macOS-only detail: other platforms simply keep the default title bar."""
    if sys.platform != "darwin":
        return
    win = _WINDOW["win"]
    if win is None or win.native is None:
        return
    import AppKit
    from PyObjCTools import AppHelper

    def run():
        w = win.native
        r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
        c = AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, 1.0)
        w.setTitlebarAppearsTransparent_(True)
        w.setBackgroundColor_(c)
        w.setAppearance_(AppKit.NSAppearance.appearanceNamed_(AppKit.NSAppearanceNameDarkAqua))
        try:   # pywebview paints the title bar view the system gray: clear it so the window color shows
            w.contentView().superview().subviews().lastObject().setBackgroundColor_(AppKit.NSColor.clearColor())
        except Exception:
            pass
    AppHelper.callAfter(run)


@app.post("/api/window/titlebar")
def window_titlebar(color: str = Body(..., embed=True)):
    if not _HEX.fullmatch(color or ""):
        raise HTTPException(400, "color must be #rrggbb")
    if _WINDOW["win"] is None:
        return {"ok": False, "window": False}
    _paint_titlebar(color)
    geo = _WINDOW["geo"]
    try:   # remembered, so the next launch opens in the theme color instead of flashing gray
        with open(geo) as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    d["titlebar"] = color
    try:
        with open(geo, "w") as f:
            json.dump(d, f)
    except OSError:
        pass
    return {"ok": True, "window": True}


@app.post("/api/window/quit")
def window_quit():
    """Persist the app's unfinished queue before its native window closes."""
    gen.on_quit(save=True)
    return {"ok": True}


app.mount("/", StaticFiles(directory=os.path.join(HERE, "web"), html=True), name="web")


def _mac_branding():
    try:
        from AppKit import NSApplication, NSImage
        from Foundation import NSBundle
        info = NSBundle.mainBundle().localizedInfoDictionary() or NSBundle.mainBundle().infoDictionary()
        if info is not None:
            info["CFBundleName"] = "Spellbook UI"
        icon = os.path.join(HERE, "icon.png")
        if os.path.exists(icon):
            NSApplication.sharedApplication().setApplicationIconImage_(NSImage.alloc().initByReferencingFile_(icon))
    except Exception:
        pass


def _is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True


def _find_available_port(start_port: int, max_attempts: int = 10, host: str = "127.0.0.1") -> int:
    for p in range(start_port, start_port + max_attempts):
        if not _is_port_in_use(p, host):
            return p
    return start_port


if __name__ == "__main__":
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=7872)
    ap.add_argument("--window", action="store_true")
    ap.add_argument("--no-window", action="store_true", help="run as a pure web server; open http://127.0.0.1:PORT in any browser")
    ap.add_argument("--native-window", action="store_true")
    a = ap.parse_args()
    if a.window or a.native_window:
        gen.restore_queue(os.path.join(APP_DIR, "queue.json"))

    port = a.port
    # When launched by the native Swift launcher, the launcher has already verified the port is free.
    # Don't re-check and switch ports, which would cause the launcher's health check to fail.
    if not (a.window or a.native_window):
        if _is_port_in_use(port):
            new_port = _find_available_port(port, max_attempts=10)
            if new_port != port:
                print(f"Notice: Port {port} is busy. Using port {new_port} instead.", flush=True)
                port = new_port
            else:
                print(f"Warning: Port {port} is in use and no alternative open port was found.", file=sys.stderr, flush=True)

    cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(cfg)
    if not a.window or a.native_window:
        print(f"Spellbook UI is ready: http://127.0.0.1:{port}/  (open this in your browser; Ctrl+C to quit)", flush=True)
        server.run()
    else:
        import time
        import webview
        t = threading.Thread(target=server.run, daemon=True)
        t.start()
        t0 = time.time()
        while not server.started:
            if not t.is_alive() or (time.time() - t0) > 10.0:
                print(f"Error: Server failed to start on port {port}.", file=sys.stderr, flush=True)
                sys.exit(1)
            time.sleep(0.05)
        _mac_branding()
        geo_path = os.path.join(APP_DIR, "window.json")
        try:
            with open(geo_path) as f:
                geo = json.load(f)
        except (OSError, ValueError):
            geo = {}
        win = webview.create_window("Spellbook UI", f"http://127.0.0.1:{port}/", width=int(geo.get("width", 1500)),
                                    height=int(geo.get("height", 980)), x=geo.get("x"), y=geo.get("y"),
                                    min_size=(1080, 680), background_color=geo.get("titlebar") or "#0d0e10")
        _WINDOW.update(win=win, geo=geo_path)
        win.events.shown += lambda: _paint_titlebar(geo.get("titlebar") or "#0d0e10")

        def _remember(*_):  # window size and position for next launch
            try:
                with open(geo_path) as f:
                    keep = {k: v for k, v in json.load(f).items() if k == "titlebar"}
            except (OSError, ValueError):
                keep = {}
            try:
                with open(geo_path, "w") as f:
                    json.dump({"width": win.width, "height": win.height, "x": win.x, "y": win.y, **keep}, f)
            except Exception:
                pass
        def _ask_save():
            """Like a normal Mac app: unfinished jobs? Save / Don't Save / Cancel before quitting (window close or ⌘Q).
            Non-macOS has no NSAlert here, so unfinished jobs are paused and saved automatically instead."""
            jobs, images = gen.unfinished()
            if not jobs:
                return None
            if sys.platform == "darwin":
                import AppKit
                alert = AppKit.NSAlert.alloc().init()
                alert.setMessageText_("Save this session?")
                alert.setInformativeText_(f"You have {jobs} unfinished job{'s' if jobs != 1 else ''} ({images} image{'s' if images != 1 else ''}). "
                                          "Save them to continue next time? They'll come back paused, with Resume.\n\n"
                                          "Your Generate settings are always kept.")
                for label in ("Save", "Don't Save", "Cancel"):
                    alert.addButtonWithTitle_(label)
                choice = alert.runModal()           # 1000 Save, 1001 Don't Save, 1002 Cancel
                if choice == 1002:
                    return False                    # stay open
                gen.on_quit(save=choice == 1000)
            else:
                gen.on_quit(save=True)              # other platforms: keep the session, safe default
            return None
        win.events.resized += _remember
        win.events.moved += _remember
        win.events.closing += _remember
        win.events.closing += _ask_save
        webview.start(private_mode=False)   # persistent WKWebView store: keeps localStorage (theme, prefs, Generate settings) between launches
        server.should_exit = True
        os._exit(0)

