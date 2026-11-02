"""Prompt Library — standalone local app (no Forge needed).

Reuses lib_pl from the Forge extension (one source of truth). Tabs: Interrogate image → prompt, Browse the
Civitai library, Tag Cleaner. Every prompt box has a copy button. Run: venv/bin/python app.py [--port 7870]."""
import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

EXT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EXT_DIR)

import gradio as gr  # noqa: E402
from PIL import Image  # noqa: E402

from lib_pl.krita import to_krita  # noqa: E402
from lib_pl.favorites import Favorites  # noqa: E402
from lib_pl.tagclean import split_top  # noqa: E402
from lib_pl.poses import detect as detect_pose, presets as pose_presets, swap as swap_pose  # noqa: E402
import urllib.request  # noqa: E402
from lib_pl.interrogate import CLAUDE, ENGINES, LOCAL, TAGS_ONLY, interrogate  # noqa: E402
from lib_pl.library import (BASES, RATINGS, TAG_THEMES, THEMES, Library, ThumbCache, can_run,  # noqa: E402
                            lora_status, record_settings)
from lib_pl.presets import load_presets  # noqa: E402
from lib_pl.tagclean import clean  # noqa: E402
from lib_pl.tagger import TAGGER_REPOS, Tagger, download  # noqa: E402
from lib_pl.writer_claude import ClaudeWriter  # noqa: E402
from lib_pl.writer_ollama import OllamaWriter  # noqa: E402

FORGE = os.path.expanduser("~/stable-diffusion-webui-forge")
APP_DIR = os.path.abspath(os.path.expanduser(os.environ.get("SPELLBOOK_APP_DIR") or os.path.join(os.path.dirname(os.path.dirname(__file__)), ".beta-data")))
SETTINGS_PATH = os.path.join(APP_DIR, "settings.json")
PRESETS_PATH = os.path.join(EXT_DIR, "presets.json")
DEFAULTS = {
    "library_path": os.path.expanduser(paths.library_dir()),
    "lora_dir": os.path.join(FORGE, "models", "Lora"),
    "tagger_dir": os.path.join(FORGE, "models", "prompt-library"),  # shares Forge's downloaded tagger
    "tagger": "wd-vit-tagger-v3",
    "general_threshold": 0.35,
    "character_threshold": 0.85,
    "ollama_url": "http://127.0.0.1:11434",
    "ollama_model": "qwen2.5vl:7b",
    "claude_model": "claude-sonnet-5-5",
}
PER_PAGE = 60


def settings():
    s = dict(DEFAULTS)
    try:
        with open(SETTINGS_PATH) as f:
            s.update(json.load(f))
    except (OSError, ValueError):
        pass
    return s


S = settings()
os.makedirs(APP_DIR, exist_ok=True)
if not os.path.exists(SETTINGS_PATH):
    with open(SETTINGS_PATH, "w") as f:
        json.dump(S, f, indent=1)

_state = {"tagger": None, "lib": None}
FAV = Favorites(os.path.join(APP_DIR, "favorites.json"))
KRITA_BRIDGE = "http://127.0.0.1:8767"
_pool = ThreadPoolExecutor(8)
thumbs = ThumbCache(os.path.join(APP_DIR, "thumbs"))
placeholder = os.path.join(APP_DIR, "thumbs", "_placeholder.png")
if not os.path.exists(placeholder):
    Image.new("RGB", (320, 480), (40, 40, 48)).save(placeholder)


class ThresholdTagger:
    def __init__(self, tagger):
        self.tagger = tagger

    def tag(self, image):
        return self.tagger.tag(image, S["general_threshold"], S["character_threshold"])


def get_tagger():
    if _state["tagger"] is None:
        model, tags = download(S["tagger"], S["tagger_dir"])
        _state["tagger"] = Tagger(model, tags)
    return _state["tagger"]


def library():
    if _state["lib"] is None:
        _state["lib"] = Library(S["library_path"])
    return _state["lib"]


def preset_names():
    return list(load_presets(PRESETS_PATH))


# ---------------------------------------------------------------- interrogate
def run_interrogate(image, preset_name, engine):
    if image is None:
        return "", "", "", "Drop an image first.", ""
    presets = load_presets(PRESETS_PATH)
    if preset_name not in presets:
        return "", "", "", f"Unknown preset: {preset_name}", ""
    try:
        tagger = ThresholdTagger(get_tagger())
    except Exception as e:
        return "", "", "", f"Tagger failed to load: {e}", ""
    writers = {LOCAL: OllamaWriter(S["ollama_url"], S["ollama_model"]),
               CLAUDE: ClaudeWriter(os.environ.get("ANTHROPIC_API_KEY", S.get("anthropic_key", "")), S["claude_model"])}
    img = image if isinstance(image, Image.Image) else Image.fromarray(image)
    try:
        r = interrogate(img, presets[preset_name], engine, tagger, writers)
    except Exception as e:
        return "", "", "", f"Interrogate failed: {e.__class__.__name__}: {e}", ""
    md = " · ".join(f"**{k}** {v}" for k, v in r.settings.items())
    return r.prompt, r.negative, md, r.notes, r.character


# ---------------------------------------------------------------- browse
def do_search(query, base, theme, rating, sort="Most reactions", per_page=PER_PAGE, collection="All", runnable=False,
              seed=0, page=0):
    L = library()
    if L.error:
        return [], [], L.error, 0, 1
    per_page = int(per_page or PER_PAGE)
    checks = []
    if collection and collection != "All":
        ids_ = FAV.ids(collection)
        checks.append(lambda r: r["id"] in ids_)
    if runnable:
        checks.append(lambda r: can_run(r, S["lora_dir"]))
    keep = (lambda r: all(c(r) for c in checks)) if checks else None
    rows, total, page = L.page(query, base, theme, rating, int(page or 0), per_page, sort, int(seed or 0), keep)
    paths = list(_pool.map(lambda r: thumbs.path(r["id"]), rows))
    gallery = [(p or placeholder, f"#{r['id']} · {r.get('base') or '?'} · {r.get('react') or 0:,}") for p, r in zip(paths, rows)]
    pages = max(1, -(-total // per_page))
    first = page * per_page + 1 if total else 0
    status = f"**{total:,}** results · showing {first:,}–{page * per_page + len(rows):,} · page **{page + 1}** of **{pages}**"
    return gallery, [r["id"] for r in rows], status, page, page + 1


def do_select(ids, evt: gr.SelectData):
    empty = ("", "", "Record no longer in library — search again.", "", "", "", gr.update(choices=[], value=None), None,
             gr.update(), "", "", "", gr.update(), None, "", "")
    try:
        r = library().by_id[ids[evt.index]]
    except (KeyError, IndexError, TypeError):
        return empty
    st = record_settings(r)[2]
    cfg = f"Distilled CFG {st['distilled_cfg']}" if "distilled_cfg" in st else f"CFG {st['cfg']}"
    loras = lora_status(r.get("res", []), S["lora_dir"])
    lora_md = "\n".join(f"- {'✅' if ok else '⚠️ not installed'} {n} @ {w}" for n, w, ok in loras) or "- none"
    hero = f" · hero: {r['hero']}" if r.get("hero") else ""
    runnable = "✅ you can run this" if can_run(r, S["lora_dir"]) else "⚠️ needs a model/LoRA you don't have"
    md = (f"**#{r['id']}** · {r.get('base') or '?'} · rating {r.get('nsfw')} · {r.get('react') or 0:,} reactions{hero} · "
          f"[open on Civitai](https://civitai.com/images/{r['id']}) · {runnable}\n\n"
          f"**Settings:** {st['sampler']} · {st.get('scheduler') or 'Automatic'} · {st['steps']} steps · {cfg} · "
          f"{st['width']}x{st['height']} · clip skip {st.get('clip_skip') or '-'}\n\n**LoRAs**\n{lora_md}")
    kp, kn, style, notes = to_krita(r["prompt"], r.get("neg", ""), r.get("base") or "", r.get("nsfw"))
    w, h = st["width"], st["height"]
    canvas = "832×1216" if h > w else ("1216×832" if w > h else "1024×1024")
    kmd = (f"**Suggested Krita style:** {style}  \n**Canvas:** {canvas}  \n" + "  \n".join(f"· {n}" for n in notes))
    tags = [t for t in split_top(kp) if 2 < len(t) < 40][:40]
    where = FAV.where(r["id"])
    fav_md = ("In: " + ", ".join(where)) if where else "Not saved yet."
    pose, _ = detect_pose(kp)
    return (r["prompt"], r.get("neg", ""), md, kp, kn, kmd, gr.update(choices=tags, value=None), r["id"],
            gr.update(choices=FAV.names(), value=(where[0] if where else Favorites.DEFAULT)), FAV.note(r["id"]), fav_md,
            style.split(" (needs")[0], gr.update(selected_index=evt.index), thumbs.path(r["id"]),
            f"**Selected #{r['id']}** · {r.get('react') or 0:,} reactions", ", ".join(pose))


POSES = pose_presets()


def send_pose(label):
    p = POSES.get(label)
    if not p or not p.get("skeleton"):
        return "Pick a Pose Kit preset first."
    body = json.dumps({"path": p["skeleton"], "name": label}).encode()
    try:
        req = urllib.request.Request(f"{KRITA_BRIDGE}/pose", body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            res = json.load(r)
    except Exception:
        return "⚠️ Krita isn't reachable — open Krita and a document (restart Krita once after updates)."
    if not res.get("ok"):
        return f"⚠️ {res.get('error')}"
    return f"✅ Added hidden layer **{res['layer']}** as a Pose control in Krita" + (f" · {res['note']}" if res.get("note") else "")


def pick_pose(label):
    p = POSES.get(label)
    if not p:
        return gr.update(), None, ""
    note = f"**{label}** — {p['note']}  \nCanvas **{p['canvas'].replace('x', '×')}** · drag the skeleton into Krita → Pose control layer"
    return p["tags"], p["skeleton"], note


def apply_pose(krita_prompt, pose_tags):
    if not (krita_prompt or "").strip():
        return gr.update(), "Select a result first."
    return swap_pose(krita_prompt, pose_tags), "✅ Pose tags swapped in the Krita prompt."


def save_fav(rid, collection, note):
    if rid is None:
        return "Click a result first.", gr.update(), gr.update()
    name = FAV.add(collection, rid, note)
    names = ["All"] + FAV.names()
    return f"Saved to **{name}** · in: {', '.join(FAV.where(rid))}", gr.update(choices=FAV.names(), value=name), gr.update(choices=names)


def remove_fav(rid, collection):
    if rid is None:
        return "Click a result first."
    FAV.remove(collection, rid)
    where = FAV.where(rid)
    return ("Removed. In: " + ", ".join(where)) if where else "Removed — not in any collection now."


def send_to_krita(prompt, negative, style):
    body = json.dumps({"prompt": prompt or "", "negative": negative or "", "style": style or ""}).encode()
    try:
        req = urllib.request.Request(f"{KRITA_BRIDGE}/prompt", body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            res = json.load(r)
    except Exception:
        return "⚠️ Krita isn't reachable — open Krita (with the AI Prompt Bridge add-on enabled) and a document."
    if not res.get("ok"):
        return f"⚠️ {res.get('error')}"
    return f"✅ Sent to Krita · style: **{res.get('style')}**" + (f" · {res['note']}" if res.get("note") else "")


# ---------------------------------------------------------------- tag cleaner
def do_clean(text, kind, framing):
    out, notes = clean(text or "", positive=(kind == "Positive prompt"), framing=framing)
    return out, ("\n".join(notes) if notes else "No changes — already clean.")


# ---------------------------------------------------------------- UI
def build():
    presets = preset_names()
    css = """
#pl-sticky {position: sticky; top: 0; z-index: 50; background: var(--background-fill-primary);
            padding: 6px 4px 4px; border-bottom: 1px solid var(--border-color-primary);}
#pl-sticky .form, #pl-nav-bottom .form {gap: 6px;}
.pl-nav button {min-width: 72px !important;}
.pl-status p {margin: 0 !important; white-space: nowrap;}
#pl-gallery .thumbnail-item.selected, #pl-gallery button.selected {outline: 5px solid #FFD45C !important; outline-offset: -5px;
            box-shadow: 0 0 0 3px #4B2FD6 !important; border-radius: 10px;}
"""
    with gr.Blocks(title="Prompt Library", analytics_enabled=False, theme=gr.themes.Soft(), css=css) as demo:
        gr.Markdown("## Prompt Library\nImage → prompt · Civitai library · Tag cleaner. Every prompt box has a copy button (top-right).")
        with gr.Tab("Interrogate"):
            with gr.Row():
                with gr.Column(scale=1):
                    img = gr.Image(label="Drop image", type="pil", image_mode="RGBA", height=420, show_download_button=False,
                                   show_fullscreen_button=False)
                    with gr.Row():
                        preset = gr.Dropdown(presets, value=presets[0], label="Target preset", scale=5)
                        refresh = gr.Button("🔄", scale=0, min_width=44)
                    engine = gr.Dropdown(ENGINES, value=TAGS_ONLY, label="Engine (Tags only is instant; Local needs Ollama)")
                    go = gr.Button("Interrogate", variant="primary")
                with gr.Column(scale=2):
                    out_prompt = gr.Textbox(label="Prompt", lines=7, show_copy_button=True)
                    out_neg = gr.Textbox(label="Negative prompt", lines=3, show_copy_button=True)
                    out_char = gr.Textbox(label="Character tags only (paste into a Krita style)", lines=2, show_copy_button=True)
                    out_settings = gr.Markdown()
                    out_notes = gr.Textbox(label="Notes", lines=3, interactive=False)
            go.click(run_interrogate, [img, preset, engine], [out_prompt, out_neg, out_settings, out_notes, out_char])
            refresh.click(lambda cur: gr.update(choices=preset_names(), value=cur if cur in preset_names() else preset_names()[0]),
                          [preset], [preset])
        with gr.Tab("Browse library"):
            with gr.Column(elem_id="pl-sticky"):
                with gr.Row(equal_height=True):
                    q = gr.Textbox(label="Search text or hero", scale=3, container=True)
                    base = gr.Dropdown(["All"] + BASES, value="All", label="Base", scale=1, min_width=110)
                    theme = gr.Dropdown(["All"] + list(THEMES) + TAG_THEMES, value="All", label="Theme", scale=2, min_width=160)
                    rating = gr.Dropdown(RATINGS, value="SFW", label="Rating", scale=1, min_width=120)
                    sort = gr.Dropdown(Library.SORTS, value="Most reactions", label="Sort", scale=1, min_width=140)
                    per_page = gr.Dropdown([60, 120, 240, 480], value=120, label="Per page", scale=0, min_width=100)
                    collection = gr.Dropdown(["All"] + FAV.names(), value="All", label="Collection", scale=1, min_width=140)
                    runnable = gr.Checkbox(value=False, label="Only what I can run", scale=0, min_width=150)
                    search = gr.Button("Search", variant="primary", scale=0, min_width=100)
                with gr.Row(equal_height=True, elem_classes="pl-nav"):
                    first_b = gr.Button("⏮", scale=0, size="sm")
                    prev_b = gr.Button("◀ Prev", scale=0, size="sm")
                    page_no = gr.Number(value=1, show_label=False, precision=0, minimum=1, scale=0, min_width=70, container=False)
                    go_b = gr.Button("Go", scale=0, size="sm")
                    next_b = gr.Button("Next ▶", scale=0, size="sm")
                    last_b = gr.Button("⏭", scale=0, size="sm")
                    status = gr.Markdown(elem_classes="pl-status")
            ids, page, seed = gr.State([]), gr.State(0), gr.State(0)
            gallery = gr.Gallery(columns=8, height="auto", allow_preview=False, show_label=False, object_fit="cover", elem_id="pl-gallery",
                                 show_download_button=False, show_share_button=False, show_fullscreen_button=False)
            with gr.Row(equal_height=True, elem_classes="pl-nav", elem_id="pl-nav-bottom"):
                first_b2 = gr.Button("⏮ First", scale=0, size="sm")
                prev_b2 = gr.Button("◀ Prev", scale=0, size="sm")
                next_b2 = gr.Button("Next ▶", scale=0, size="sm")
                last_b2 = gr.Button("Last ⏭", scale=0, size="sm")
                status2 = gr.Markdown(elem_classes="pl-status")
            with gr.Row(equal_height=True):
                sel_img = gr.Image(show_label=False, height=150, width=110, interactive=False, scale=0, min_width=110,
                                   show_download_button=False, show_fullscreen_button=False)
                sel_md = gr.Markdown("### Selected prompt\nClick a result above.")
            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("**Original** (Forge / Civitai)")
                    b_prompt = gr.Textbox(label="Prompt", lines=6, show_copy_button=True)
                    b_neg = gr.Textbox(label="Negative prompt", lines=3, show_copy_button=True)
                    b_md = gr.Markdown()
                    with gr.Group():
                        with gr.Row(equal_height=True):
                            fav_col = gr.Dropdown(FAV.names(), value=Favorites.DEFAULT, allow_custom_value=True,
                                                  label="Collection (type a new name to create one)", scale=2)
                            fav_save = gr.Button("⭐ Save", variant="primary", scale=0, min_width=90)
                            fav_rm = gr.Button("Remove", scale=0, min_width=90)
                        fav_note = gr.Textbox(label="Note", lines=1, placeholder="e.g. great for Sakura sheets")
                        fav_md = gr.Markdown()
                with gr.Column(scale=1):
                    gr.Markdown("**Krita** (paste with a Krita style — it adds quality tags + LoRAs)")
                    k_prompt = gr.Textbox(label="Krita prompt", lines=6, show_copy_button=True)
                    k_neg = gr.Textbox(label="Krita negative (optional — styles have their own)", lines=3, show_copy_button=True)
                    k_md = gr.Markdown()
                    with gr.Accordion("🧍 Pose — edit or swap", open=True):
                        pose_tags = gr.Textbox(label="Pose tags in this prompt (edit freely)", lines=2, show_copy_button=True)
                        with gr.Row():
                            pose_pick = gr.Dropdown(list(POSES), value=None, label="…or pick a Pose Kit preset", scale=3)
                            pose_apply = gr.Button("Swap into Krita prompt", variant="secondary", scale=1)
                        with gr.Row(equal_height=True):
                            pose_img = gr.Image(show_label=False, height=200, interactive=False, scale=0, min_width=140,
                                                show_download_button=False, show_fullscreen_button=False)
                            with gr.Column():
                                pose_md = gr.Markdown()
                                pose_send = gr.Button("➜ Send skeleton to Krita (as Pose control)", variant="secondary")
                                pose_status = gr.Markdown()
                    with gr.Row(equal_height=True):
                        k_send = gr.Button("➜ Send to Krita", variant="primary", scale=0, min_width=150)
                        k_status = gr.Markdown()
            tag_pick = gr.Radio([], label="Tags in this prompt — click one to find every prompt that uses it", interactive=True)
            sel_id, k_style = gr.State(None), gr.State("")
            filt = [q, base, theme, rating, sort, per_page, collection, runnable, seed]

            def run(*a):
                g, i_, st_, pg, no = do_search(*a)
                return g, i_, st_, pg, no, st_
            outs = [gallery, ids, status, page, page_no, status2]

            def new_search(*a):  # fresh shuffle order each time Search is pressed
                import random
                s_ = random.randint(1, 10**9)
                return (s_,) + run(*a[:8], s_, 0)
            for trigger in (search.click, q.submit, sort.change, per_page.change, collection.change, runnable.change):
                trigger(new_search, filt[:8], [seed] + outs)
            for b in (first_b, first_b2):
                b.click(lambda *a: run(*a, 0), filt, outs)
            for b in (prev_b, prev_b2):
                b.click(lambda *a: run(*a[:9], a[9] - 1), filt + [page], outs)
            for b in (next_b, next_b2):
                b.click(lambda *a: run(*a[:9], a[9] + 1), filt + [page], outs)
            for b in (last_b, last_b2):
                b.click(lambda *a: run(*a, 10**9), filt, outs)
            for trigger in (go_b.click, page_no.submit):
                trigger(lambda *a: run(*a[:9], int(a[9] or 1) - 1), filt + [page_no], outs)
            gallery.select(do_select, [ids], [b_prompt, b_neg, b_md, k_prompt, k_neg, k_md, tag_pick, sel_id, fav_col,
                                              fav_note, fav_md, k_style, gallery, sel_img, sel_md, pose_tags])
            pose_pick.change(pick_pose, [pose_pick], [pose_tags, pose_img, pose_md])
            pose_apply.click(apply_pose, [k_prompt, pose_tags], [k_prompt, pose_md])
            pose_send.click(send_pose, [pose_pick], [pose_status])
            fav_save.click(save_fav, [sel_id, fav_col, fav_note], [fav_md, fav_col, collection])
            fav_rm.click(remove_fav, [sel_id, fav_col], [fav_md])
            k_send.click(send_to_krita, [k_prompt, k_neg, k_style], [k_status])

            def tag_search(tag, *a):
                if not tag:
                    return (gr.update(),) * (len(outs) + 2)
                import random
                s_ = random.randint(1, 10**9)
                return (tag, s_) + run(tag, *a[1:8], s_, 0)
            tag_pick.input(tag_search, [tag_pick] + filt[:8], [q, seed] + outs)
        with gr.Tab("Tag Cleaner"):
            with gr.Row():
                with gr.Column():
                    t_in = gr.Textbox(label="Paste a prompt", lines=8)
                    with gr.Row():
                        t_kind = gr.Radio(["Positive prompt", "Negative prompt"], value="Positive prompt", label="Type")
                        t_frame = gr.Checkbox(value=True, label="Keep only the first framing tag")
                    t_go = gr.Button("Clean", variant="primary")
                with gr.Column():
                    t_out = gr.Textbox(label="Cleaned", lines=8, show_copy_button=True)
                    t_notes = gr.Textbox(label="What changed", lines=6, interactive=False)
            t_go.click(do_clean, [t_in, t_kind, t_frame], [t_out, t_notes])
        gr.Markdown(f"<small>Settings: `{SETTINGS_PATH}` · Presets and code shared with the Forge extension.</small>")
    return demo


def _mac_branding():
    """Dock icon + menu-bar name 'Prompt Library' instead of 'Python' (window mode on macOS)."""
    try:
        from AppKit import NSApplication, NSImage
        from Foundation import NSBundle
        info = NSBundle.mainBundle().localizedInfoDictionary() or NSBundle.mainBundle().infoDictionary()
        if info is not None:
            info["CFBundleName"] = "Prompt Library"
        icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")
        if os.path.exists(icon):
            NSApplication.sharedApplication().setApplicationIconImage_(NSImage.alloc().initByReferencingFile_(icon))
    except Exception:
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=7872)
    ap.add_argument("--window", action="store_true", help="open in a native window (closing it quits)")
    a = ap.parse_args()
    demo = build().queue()
    kw = dict(server_name="127.0.0.1", server_port=a.port, inbrowser=False, show_api=False,
              allowed_paths=[APP_DIR, os.path.join(FORGE, "models", "prompt-library"),
                             os.path.expanduser(os.environ.get("SPELLBOOK_POSE_KIT") or
                                                os.path.join(os.path.dirname(os.path.dirname(__file__)), ".pose-kit"))])
    if not a.window:
        demo.launch(**kw)
    else:
        import webview
        _mac_branding()
        demo.launch(prevent_thread_lock=True, **kw)
        webview.create_window("Prompt Library", f"http://127.0.0.1:{a.port}", width=1440, height=960, min_size=(900, 600))
        webview.start()
        demo.close()
        os._exit(0)
