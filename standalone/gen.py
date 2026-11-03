"""Generate tab backend: txt2img through Forge's API (Forge started with --api), results kept in the app's own gallery."""
import asyncio
import atexit
import base64
import json
import os
import re
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request

import httpx

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import FileResponse

router = APIRouter(prefix="/api/gen")
_styles = {"list": [], "mtime": None}


def styles():
    """Styles, reloaded when either styles folder changes (Spellbook's own plus the Krita fallback)."""
    from lib_pl import kstyles
    dirs = [kstyles.STYLES_DIR, kstyles.FALLBACK_DIR]
    stamps = []
    for d in dirs:
        try:
            stamps.append((d, os.path.getmtime(d)))
        except OSError:
            stamps.append((d, None))
    if stamps != _styles["mtime"]:
        _styles.update(list=kstyles.load(), mtime=stamps)
    return _styles["list"]


def style_by_name(name):
    from lib_pl.kstyles import current_name
    return next((s for s in styles() if s["name"] in (name, current_name(name))), None)
CFG = {"forge_url": "http://127.0.0.1:7860", "out_dir": "", "lora_dir": "",
       "export_dir": os.path.expanduser("~/Pictures/Prompt Library")}
# Job queue: jobs run one at a time in a worker thread; the UI can add, cancel and watch them.
_queue = []          # [{id, label, params, status: queued|running|done|error|cancelled, results, error, started, finished, total}]
_lock = threading.Lock()
_worker = {"thread": None, "seq": 0, "notify": True, "pause_after": False}


def configure(forge_url, out_dir, lora_dir):
    CFG.update(forge_url=forge_url.rstrip("/"), out_dir=out_dir, lora_dir=lora_dir)
    os.makedirs(out_dir, exist_ok=True)


# ---- the queue survives a restart: unfinished jobs are written to queue.json and come back paused ("held")
def _persist():
    path = CFG.get("queue_file")
    if not path:
        return
    with _lock:
        keep = [{"id": j["id"], "label": j["label"], "params": j["params"], "total": j["total"]}
                for j in _queue if j["status"] in ("queued", "running", "cancelling", "held") and j["status"] != "cancelling"]
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(keep, f)
        os.replace(tmp, path)
    except OSError:
        pass


def restore_queue(path):
    """Load jobs left from the last session as held (paused): nothing runs until Resume."""
    CFG["queue_file"] = path
    _load_speed_cache()
    try:
        with open(path) as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return 0
    with _lock:
        seen_ids = set()
        for j in saved:
            jid = j.get("id")
            if jid is None or jid in seen_ids:
                continue
            seen_ids.add(jid)
            _queue.append({"id": jid, "label": j["label"], "params": j["params"], "status": "held", "results": [], "error": None,
                           "started": 0.0, "finished": 0.0, "total": j.get("total") or 1})
    return len(saved)


def unfinished():
    """(jobs, images) still to run: queued, running or held from the last session."""
    with _lock:
        js = [j for j in _queue if j["status"] in ("queued", "running", "held")]
    return len(js), sum(j["total"] for j in js)


def on_quit(save):
    """Quitting: stop the image Forge is drawing for us, then keep the unfinished jobs for next time or forget them."""
    with _lock:
        running = any(j["status"] == "running" for j in _queue)
        if not save:
            for j in _queue:
                if j["status"] in ("queued", "held"):
                    j["status"] = "cancelled"
    if save:
        _persist()
    elif CFG.get("queue_file"):
        try:
            os.remove(CFG["queue_file"])
        except OSError:
            pass
    if running:
        try:
            _call("/sdapi/v1/interrupt", {}, timeout=3)
        except Exception:
            pass


@router.post("/resume")
def resume():
    """Run the jobs saved from the last session."""
    with _lock:
        _worker["pause_after"] = False
        n = 0
        for j in _queue:
            if j["status"] == "held":
                j["status"] = "queued"
                n += 1
    if n:
        _start_worker()
    _persist()
    return {"ok": True, "resumed": n}


_sync_client = None
_sync_client_url = None
_async_client = None
_async_client_url = None


def _get_sync_client():
    global _sync_client, _sync_client_url
    url = CFG.get("forge_url", "http://127.0.0.1:7860")
    if _sync_client is None or _sync_client.is_closed or _sync_client_url != url:
        if _sync_client and not _sync_client.is_closed:
            _sync_client.close()
        _sync_client = httpx.Client(
            base_url=url,
            headers={"Content-Type": "application/json"},
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            timeout=httpx.Timeout(10.0, connect=5.0),
        )
        _sync_client_url = url
    return _sync_client


async def _get_async_client():
    global _async_client, _async_client_url
    url = CFG.get("forge_url", "http://127.0.0.1:7860")
    if _async_client is None or _async_client.is_closed or _async_client_url != url:
        if _async_client and not _async_client.is_closed:
            await _async_client.aclose()
        _async_client = httpx.AsyncClient(
            base_url=url,
            headers={"Content-Type": "application/json"},
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            timeout=httpx.Timeout(10.0, connect=5.0),
        )
        _async_client_url = url
    return _async_client


def _call(path, payload=None, timeout=10):
    client = _get_sync_client()
    to = httpx.Timeout(timeout, connect=min(5.0, float(timeout)))
    if payload is not None:
        resp = client.post(path, json=payload, timeout=to)
    else:
        resp = client.get(path, timeout=to)
    resp.raise_for_status()
    try:
        return resp.json()
    except Exception:
        return {}


_orig_call = _call


async def _async_call(path, payload=None, timeout=10):
    if _call is not _orig_call:
        res = _call(path, payload=payload, timeout=timeout)
        if asyncio.iscoroutine(res):
            return await res
        return res
    client = await _get_async_client()
    to = httpx.Timeout(timeout, connect=min(5.0, float(timeout)))
    if payload is not None:
        resp = await client.post(path, json=payload, timeout=to)
    else:
        resp = await client.get(path, timeout=to)
    resp.raise_for_status()
    try:
        return resp.json()
    except Exception:
        return {}


def _cleanup_clients():
    global _sync_client, _async_client
    if _sync_client and not _sync_client.is_closed:
        _sync_client.close()
    if _async_client and not _async_client.is_closed:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(_async_client.aclose())
            else:
                loop.run_until_complete(_async_client.aclose())
        except Exception:
            pass


atexit.register(_cleanup_clients)


def _offline(e):
    if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 404:
        return "Forge is running without its API. Restart it (webui-user.sh now has --api)."
    if isinstance(e, urllib.error.HTTPError) and e.code == 404:
        return "Forge is running without its API. Restart it (webui-user.sh now has --api)."
    return "Forge isn't running. Click Start Forge."


_refreshing = threading.Lock()
_models_seen = {"list": None}     # last complete checkpoint list from Forge


def _checkpoint_files(models):
    """Checkpoint file names on disk, in the folder(s) Forge loads from."""
    dirs = {os.path.dirname(m.get("filename") or "") for m in models} - {""}
    found = set()
    for d in dirs:
        for root, _, files in os.walk(d):
            found |= {f for f in files if f.endswith((".safetensors", ".ckpt", ".gguf")) and not f.startswith("._")}
    return found


def _models():
    """Forge's checkpoint list. Forge only scans its folder at startup, so when files were added or removed since,
    it rescans in the background. While that runs Forge's list is incomplete, so the last complete list is
    served (asking on every call made the dropdown come up empty mid-scan)."""
    if _refreshing.locked() and _models_seen["list"] is not None:
        return _models_seen["list"]
    models = _call("/sdapi/v1/sd-models")
    listed = {os.path.basename(m.get("filename") or "") for m in models}
    if _checkpoint_files(models) != listed and _refreshing.acquire(blocking=False):
        def run():
            try:   # Forge holds API calls while it generates, so this can take a while: never wait on it
                _call("/sdapi/v1/refresh-checkpoints", {}, timeout=600)
            except Exception:
                pass
            finally:
                _refreshing.release()
        threading.Thread(target=run, daemon=True).start()
        if _models_seen["list"] is not None:
            return _models_seen["list"]
    _models_seen["list"] = models
    return models


@router.get("/model-settings")
async def model_settings(model: str):
    """Recommended sampler / scheduler / steps / CFG / clip skip for a checkpoint (Forge title), for manual mode."""
    from lib_pl.model_settings import recommend
    sha = None
    try:
        sd_models = await _async_call("/sdapi/v1/sd-models")
        sha = next((m.get("sha256") for m in sd_models if m["title"] == model), None)
    except Exception:
        pass
    cache = os.path.join(os.path.dirname(CFG["queue_file"]), "model_settings.json") if CFG.get("queue_file") else None
    return {"model": model, **recommend(model, sha, styles(), cache)}


@router.get("/options")
async def options():
    from lib_pl import kstyles
    loras = []
    try:
        loras = sorted((os.path.splitext(f)[0] for f in os.listdir(CFG["lora_dir"]) if f.endswith(".safetensors")), key=str.lower)
    except OSError:
        pass
    try:
        models = _models()
        samplers = await _async_call("/sdapi/v1/samplers")
        try:
            sched_data = await _async_call("/sdapi/v1/schedulers")
            schedulers = [s["label"] for s in sched_data]
        except Exception:
            schedulers = ["Automatic", "Karras", "Exponential", "SGM Uniform", "Simple", "Normal", "Beta"]
        upscalers = [u["name"] for u in await _async_call("/sdapi/v1/upscalers")]
        opts = await _async_call("/sdapi/v1/options")
    except Exception as e:
        return {"online": False, "error": _offline(e), "loras": loras}
    titles = [m["title"] for m in models]
    sty = []
    for st in styles():
        title = next((t for t in titles if t.split(" [")[0] == st["checkpoint"] or t.startswith(st["checkpoint"])), None)
        missing = [n for n, _ in st["loras"] if n not in loras]
        sty.append({**st, "model": title, "missing": ([st["checkpoint"]] if not title else []) + missing})
    return {"online": True, "models": titles, "model": opts.get("sd_model_checkpoint"), "styles": sty,
            "samplers": [s["name"] for s in samplers], "schedulers": schedulers,
            "upscalers": [u for u in upscalers if u.lower() != "none"], "loras": loras, "renamed": kstyles.RENAMED}


def _clean_payload(p):
    """UI params -> Forge txt2img payload (with the hires quirks Forge needs). A Krita style wraps the prompt,
    adds its LoRAs and negative; sampler/steps/CFG/checkpoint come from the UI fields (the style pre-fills them)."""
    prompt, negative = p.get("prompt", ""), p.get("negative", "")
    st = style_by_name(p.get("style")) if p.get("style") else None
    if st:
        from lib_pl import kstyles
        prompt, negative = kstyles.apply(st, prompt, negative)
    out = {
        "prompt": prompt, "negative_prompt": negative,
        "sampler_name": p.get("sampler") or "Euler a", "scheduler": p.get("scheduler") or "Automatic",
        "steps": int(p.get("steps") or 25), "cfg_scale": float(p.get("cfg") or 7),
        "width": int(p.get("width") or 832), "height": int(p.get("height") or 1216),
        "seed": int(p.get("seed") if p.get("seed") not in (None, "") else -1),
        "batch_size": 1, "n_iter": max(1, min(int(p.get("count") or 1), 16)),
        "send_images": True, "save_images": False,
        "override_settings": {}, "override_settings_restore_afterwards": False,
    }
    if p.get("model"):
        out["override_settings"]["sd_model_checkpoint"] = p["model"]
    if p.get("clip_skip"):
        out["override_settings"]["CLIP_stop_at_last_layers"] = int(p["clip_skip"])
    if p.get("distilled_cfg") is not None:
        out["distilled_cfg_scale"] = float(p["distilled_cfg"])
    if p.get("variation"):  # same composition, small changes
        out.update(subseed=-1, subseed_strength=float(p.get("variation_strength") or 0.18))
    _extras(out, p)
    if p.get("hires"):
        out.update(enable_hr=True, hr_scale=max(1.0, float(p.get("hr_scale") or 1.5)), hr_upscaler=p.get("hr_upscaler") or "Latent",
                   denoising_strength=float(p.get("hr_denoise") or 0.4), hr_second_pass_steps=int(p.get("hr_steps") or 0),
                   hr_sampler_name=out["sampler_name"], hr_scheduler=out["scheduler"],
                   hr_additional_modules=["Use same choices"])  # None -> TypeError 500 in Forge
    return out


def _b64_file(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def _cn_model(prefix):
    try:
        return next((m for m in _call("/controlnet/model_list", timeout=5).get("model_list", []) if m.startswith(prefix)), None)
    except Exception:
        return None


def _extras(out, p):
    """ADetailer face/hand fix and ControlNet pose, shared by txt2img and img2img."""
    scripts = {}
    # body first (low denoise keeps the pose), then face and hands get the final word on their details
    ad = [{"ad_model": "person_yolov8s-seg.pt", "ad_denoising_strength": float(p.get("body_denoise") or 0.35),
           "ad_mask_blur": 8, "ad_inpaint_only_masked_padding": 48}] if p.get("fix_body") else []
    ad += [{"ad_model": "face_yolov8n.pt"}] if p.get("fix_face") else []
    ad += [{"ad_model": "hand_yolov8n.pt"}] if p.get("fix_hands") else []
    if ad:   # 2nd arg = skip img2img: fix-only jobs keep the finished image and only redraw the detected areas
        scripts["ADetailer"] = {"args": [True, bool(p.get("ad_only")), *ad]}
    skel = _pose_skel(p)
    if skel:
        _back_view_tags(out, p, skel)
        model = _cn_model("xinsir_openpose_sdxl") or _cn_model("control-lora-openposeXL2")
        if model:
            # Resize and Fill: a skeleton whose shape differs from the image is shrunk and padded, never cropped (no lost limbs)
            scripts["ControlNet"] = {"args": [{
                "enabled": True, "image": _b64_file(skel), "module": "None", "model": model,
                "weight": float(p.get("pose_weight") or 0.8), "resize_mode": "Resize and Fill",
                "guidance_start": 0.0, "guidance_end": float(p.get("pose_end") or 0.8), "pixel_perfect": True,
                "control_mode": _pose_mode(p, out.get("prompt", ""))}]}
            depth = _pose_depth(p)
            dmodel = depth and (_cn_model("xinsir_depth_sdxl") or _cn_model("control-lora-depth"))
            if dmodel:  # body shape + what's in front; ends early so clothes and style still draw over it
                scripts["ControlNet"]["args"].append({
                    "enabled": True, "image": _b64_file(depth), "module": "None", "model": dmodel,
                    "weight": float(p.get("pose_depth_weight") or 0.45), "resize_mode": "Resize and Fill",
                    "guidance_start": 0.0, "guidance_end": float(p.get("pose_depth_end") or 0.55), "pixel_perfect": True,
                    "control_mode": "Balanced"})
    if scripts:
        out["alwayson_scripts"] = scripts


BACK_RE = re.compile(r"\b(from behind|from back|back view|rear view)\b", re.I)


def _back_view_tags(out, p, skel):
    """Make the prompt face the same way as the skeleton. Words that only fit the other side (breasts, navel,
    looking at viewer on a faceless back view; from behind, looking back on a front view) come out unless the
    filter is switched off; this also catches the style's own words and anything typed after the pose was picked.
    A back-view skeleton alone doesn't turn the body around (SDXL draws a front with the same limbs), so back
    poses always say so in the prompt, even with "Add the pose's tags" off."""
    if not CFG.get("pose_view"):
        return
    try:
        tags = CFG["pose_view"](p, skel)
    except Exception:
        return
    if p.get("pose_facing_filter", True):
        from lib_pl.poses import facing_filter, pose_facing
        out["prompt"], _ = facing_filter(out.get("prompt", ""), *pose_facing(tags), pose_tags=tags)
    from lib_pl.pose_features import PROMPT_TAGS
    from lib_pl.poses import pose_wins
    out["prompt"], _ = pose_wins(out.get("prompt", ""), ", ".join(PROMPT_TAGS.get(t, t) for t in tags))   # a picked pose always wins
    if "from behind" not in tags or BACK_RE.search(out.get("prompt", "")):
        return
    add = "(from behind:1.2)" + (", looking back" if "looking back" in tags and "looking back" not in out["prompt"] else "")
    out["prompt"] = f"{out['prompt'].rstrip(', ')}, {add}" if out.get("prompt") else add


def _pose_skel(p):
    """Skeleton image for the job's pose (a typed path, a pose-pack id or a Pose Kit preset), or None."""
    skel = p.get("pose_skeleton")
    if not skel and p.get("pose_pack_id") and CFG.get("pose_pack_path"):
        skel = CFG["pose_pack_path"](p["pose_pack_id"])
    if not skel and p.get("pose_key"):
        from lib_pl.poses import presets
        skel = next((v["skeleton"] for v in presets().values() if v["key"] == p["pose_key"]), None)
    return skel if skel and os.path.exists(skel) else None


def _pose_depth(p):
    """The pose's depth map when depth is switched on and the pose has one (pose packs / "From image" poses)."""
    if not p.get("pose_depth") or not p.get("pose_pack_id") or not CFG.get("pose_depth_path"):
        return None
    return CFG["pose_depth_path"](p["pose_pack_id"])


POSE_MODES = {"balanced": "Balanced", "pose": "ControlNet is more important", "prompt": "My prompt is more important"}


def _pose_mode(p, prompt):
    """ControlNet priority. Auto: LoRA-heavy prompts (2+ LoRAs) pull the body their own way, so the pose goes first."""
    m = p.get("pose_mode") or "auto"
    if m == "auto":
        m = "pose" if prompt.count("<lora:") >= 2 else "balanced"
    return POSE_MODES.get(m, "Balanced")


def _img2img_payload(p, init_path):
    """img2img for Remix (any image) and Upscale (gallery image at a bigger size)."""
    out = _clean_payload({**p, "hires": False})
    for k in ("enable_hr", "hr_scale", "hr_upscaler", "hr_second_pass_steps", "hr_sampler_name", "hr_scheduler", "hr_additional_modules"):
        out.pop(k, None)
    out.update(init_images=[_b64_file(init_path)], denoising_strength=float(p.get("denoise") or 0.45),
               resize_mode=int(p.get("resize_mode") or 0), include_init_images=False)
    return out


def _error_text(e, backend="forge"):
    if isinstance(e, (httpx.RequestError, urllib.error.URLError, ConnectionError)):
        msg = _offline(e)
    else:
        msg = f"{e.__class__.__name__}: {e}"
    if isinstance(e, httpx.HTTPStatusError):
        try:
            body = e.response.json()
            msg = body.get("detail") or body.get("error") or body.get("errors") or msg
        except Exception:
            msg = f"Generation service returned {e.response.status_code}"
    elif isinstance(e, urllib.error.HTTPError):
        try:
            body = json.loads(e.read())
            msg = body.get("detail") or body.get("error") or body.get("errors") or msg
        except Exception:
            msg = f"Forge returned {e.code}"
    msg = str(msg)
    lowered = msg.lower()
    memory_signals = ("out of memory", "not enough memory", "failed to allocate", "allocation failed",
                      "mps backend out of memory", "cuda error: out of memory", "unable to allocate memory")
    if any(signal in lowered for signal in memory_signals):
        return ("Forge ran out of available memory. No automatic retry or service restart was attempted. "
                "Try a smaller image size or fewer images, then retry. Details: " + msg[:700])
    return msg


def _run_job(job):
    params = job["params"]
    saved = _generate(job, params)
    skel = _pose_skel(params) if (params.get("mode") or "txt2img") != "upscale" else None
    if not (skel and CFG.get("pose_score") and params.get("pose_check", True)):
        return saved
    _score_pose(saved, skel, params)
    # Retry: below the bar, roll new seeds (every attempt is kept, each with its score)
    need = int(params.get("pose_min") or 0)
    tries = max(0, min(int(params.get("pose_retries") or 2), 4)) if need else 0
    attempt = 1
    while tries and job["status"] == "running" and not any(_pose_ok(m, need) for m in saved):
        tries -= 1
        attempt += 1
        with _lock:
            job["total"] += max(1, min(int(params.get("count") or 1), 16))
        more = _generate(job, {**params, "seed": -1}, attempt=attempt)
        _score_pose(more, skel, params)
        saved += more
    return saved


def _pose_ok(meta, need):
    """Good enough to stop retrying: facing the right way, and at or above the bar (an unjudgeable score passes)."""
    if str(meta.get("pose_facing") or "").startswith("wrong"):
        return False
    return meta.get("pose_score") is None or meta["pose_score"] >= need


def _score_pose(saved, skel, params):
    """Pose match % for each new image (DWPose on the result vs the skeleton), stored in its .json."""
    for meta in saved:
        try:
            r = CFG["pose_score"](skel, os.path.join(CFG["out_dir"], meta["name"]), params)
            if isinstance(r, dict):
                meta["pose_score"], meta["pose_facing"] = r.get("score"), r.get("facing")
            else:
                meta["pose_score"] = r
        except Exception as e:
            meta["pose_score"] = None
            meta["pose_error"] = str(e)[:120]
        with open(os.path.join(CFG["out_dir"], meta["name"][:-4] + ".json"), "w") as f:
            json.dump(meta, f)


def _generate(job, params, attempt=1):
    mode = params.get("mode") or "txt2img"
    if mode == "upscale":
        payload, r, params = _run_upscale(params)
    elif mode == "fix":
        payload, r, params = _run_fix(params)
    elif mode == "img2img":
        payload = _img2img_payload(params, _input_path(params["source"]))
        r = _call("/sdapi/v1/img2img", payload, timeout=60 * 60 * 3)
    else:
        payload = _clean_payload(params)
        r = _call("/sdapi/v1/txt2img", payload, timeout=60 * 60 * 3)
    info = json.loads(r.get("info") or "{}")
    seeds = info.get("all_seeds") or [info.get("seed")]
    infotexts = info.get("infotexts") or []
    saved = []
    stamp = time.strftime("%Y%m%d-%H%M%S")
    images = r.get("images", [])
    keep = len(info.get("all_seeds") or []) or (1 if params.get("mode") == "upscale" else int(payload.get("n_iter") or 1))
    for i, b64 in enumerate(images[:keep]):  # ControlNet/ADetailer append their detection maps after the real images
        with _lock:
            _worker["seq"] += 1
            n = _worker["seq"]
        name = f"{stamp}-{n}{i + 1:02d}.png"
        with open(os.path.join(CFG["out_dir"], name), "wb") as f:
            f.write(base64.b64decode(b64.split(",", 1)[-1]))
        meta = {"name": name, "job": job["id"], "time": time.time(), "params": params, "label": job["label"],
                "final_prompt": payload["prompt"], "final_negative": payload["negative_prompt"],
                "seed": seeds[i] if i < len(seeds) else None, "infotext": infotexts[i] if i < len(infotexts) else ""}
        if attempt > 1:
            meta["pose_attempt"] = attempt
        with open(os.path.join(CFG["out_dir"], name[:-4] + ".json"), "w") as f:
            json.dump(meta, f)
        saved.append(meta)
    return saved


def _run_fix(params):
    """Face / hand / body fix on a finished gallery image: ADetailer only (img2img skipped), same prompt and seed.
    The result is a new image; the original stays."""
    src = _path(params["source"])
    with open(src[:-4] + ".json") as f:
        meta = json.load(f)
    orig = meta.get("params", {})
    from PIL import Image
    with Image.open(src) as im:
        w, h = im.size
    p = {**orig, "prompt": meta.get("final_prompt") or orig.get("prompt", ""), "negative": meta.get("final_negative") or orig.get("negative", ""),
         "style": "", "seed": meta.get("seed") or -1, "count": 1, "variation": False, "hires": False, "width": w // 8 * 8, "height": h // 8 * 8,
         "fix_face": params.get("fix_face"), "fix_hands": params.get("fix_hands"), "fix_body": params.get("fix_body"), "ad_only": True,
         "pose_skeleton": None, "pose_key": None, "pose_pack_id": None, "denoise": 0.4}
    if not (p["fix_face"] or p["fix_hands"] or p["fix_body"]):
        raise ValueError("Pick at least one fix")
    payload = _img2img_payload(p, src)
    r = _call("/sdapi/v1/img2img", payload, timeout=60 * 60)
    eff = {**orig, "mode": "fix", "source": params["source"], "fix_face": p["fix_face"], "fix_hands": p["fix_hands"], "fix_body": p["fix_body"],
           "pose_skeleton": None, "pose_key": None, "pose_pack_id": None}
    return payload, r, eff


def _run_upscale(params):
    """Enlarge a gallery image with an upscaler model, then a low-denoise img2img pass redraws fine detail."""
    src = _path(params["source"])
    with open(src[:-4] + ".json") as f:
        meta = json.load(f)
    orig = meta.get("params", {})
    scale = max(1.1, min(float(params.get("scale") or 1.5), 3.0))
    up = _call("/sdapi/v1/extra-single-image", {"image": _b64_file(src), "upscaling_resize": scale,
                                                 "upscaler_1": params.get("upscaler") or "R-ESRGAN 4x+ Anime6B"}, timeout=60 * 30)
    tmp = os.path.join(CFG["out_dir"], "inputs")
    os.makedirs(tmp, exist_ok=True)
    big = os.path.join(tmp, f"up-{int(time.time())}.png")
    with open(big, "wb") as f:
        f.write(base64.b64decode(up["image"].split(",", 1)[-1]))
    from PIL import Image
    with Image.open(big) as im:
        w, h = im.size
    p = {**orig, "prompt": meta.get("final_prompt") or orig.get("prompt", ""), "negative": meta.get("final_negative") or orig.get("negative", ""),
         "style": "", "seed": meta.get("seed") or -1, "count": 1, "variation": False,
         "width": w // 8 * 8, "height": h // 8 * 8, "denoise": float(params.get("denoise") or 0.3),
         "fix_face": params.get("fix_face"), "fix_hands": params.get("fix_hands"), "fix_body": params.get("fix_body"), "pose_skeleton": None, "pose_key": None, "pose_pack_id": None}
    payload = _img2img_payload(p, big)
    r = _call("/sdapi/v1/img2img", payload, timeout=60 * 60 * 3)
    try:
        os.remove(big)
    except OSError:
        pass
    eff = {**p, "mode": "upscale", "source": params["source"], "scale": scale, "upscaler": params.get("upscaler")}
    return payload, r, eff


def _input_path(name):
    if not re.fullmatch(r"(in-\d+-\d+\.png|\d{8}-\d{6}-\d+\.png)", name or ""):
        raise HTTPException(400, "Bad source")
    p = os.path.join(CFG["out_dir"], "inputs", name) if name.startswith("in-") else os.path.join(CFG["out_dir"], name)
    if not os.path.exists(p):
        raise HTTPException(404, "Source image not found")
    return p


@router.post("/input")
async def upload_input(request: Request):
    """Remix source: raw image bytes in the body -> saved under generations/inputs, returns its name."""
    data = await request.body()
    from PIL import Image
    import io
    try:
        im = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        raise HTTPException(400, "That isn't an image")
    os.makedirs(os.path.join(CFG["out_dir"], "inputs"), exist_ok=True)
    with _lock:
        _worker["seq"] += 1
        n = _worker["seq"]
    name = f"in-{int(time.time())}-{n}.png"
    im.save(os.path.join(CFG["out_dir"], "inputs", name))
    return {"name": name, "width": im.width, "height": im.height}


@router.get("/input/{name}")
def input_image(name: str):
    return FileResponse(_input_path(name))


# Optional notifier helper inside local app bundle (built by notifier/build.sh).
# The path is a stable local convention: environments without it simply skip notifications.
NOTIFIER = os.path.expanduser("~/Applications/Spellbook Beta.app/Contents/Helpers/Spellbook Beta.app/Contents/MacOS/SpellbookNotifier")


def _notify(title, text):
    import subprocess
    if sys.platform != "darwin":
        return  # desktop notifications are macOS for now
    if os.access(NOTIFIER, os.X_OK):
        subprocess.Popen([NOTIFIER, title, text, "Glass"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    script = f'display notification "{text}" with title "{title}" sound name "Glass"'   # fallback: Script Editor icon
    subprocess.run(["osascript", "-e", script], check=False, timeout=5)


def _job_model(job):
    """Checkpoint a job will load ("" when it uses whatever is loaded)."""
    return ((job.get("params") or {}).get("model") or "").split(" [")[0]


def _loaded_forge_model():
    """Read Forge's active checkpoint once when a fresh generation worker starts."""
    try:
        model = _call("/sdapi/v1/options", timeout=15).get("sd_model_checkpoint") or ""
        return model.split(" [")[0]
    except Exception:
        return ""


def _next_job(queue, loaded):
    """Next job to run: the first queued one, except that jobs for the already-loaded checkpoint go first.
    Switching an SDXL checkpoint costs 15-30 s on a Mac, so a mixed queue (A, B, A, B) runs as A, A, B, B.
    The chosen job is moved up in the list, so the queue the UI shows is the order things really run in."""
    queued = [j for j in queue if j["status"] == "queued"]
    if not queued:
        return None
    job = queued[0]
    if loaded and _job_model(job) not in ("", loaded):
        job = next((j for j in queued if _job_model(j) in ("", loaded)), job)
    if job is not queued[0]:
        queue.remove(job)
        queue.insert(queue.index(queued[0]), job)
    return job


def _loop():
    done_any = False
    # Order the first queue against the checkpoint Forge already has loaded.
    # The generation worker only reads Forge state here; lifecycle changes require an explicit app action.
    if not _worker.get("model_initialized"):
        _worker["model"] = _loaded_forge_model()
        _worker["model_initialized"] = True
    while True:
        with _lock:
            if _worker.get("pause_after"):
                _worker["thread"] = None
                _worker["pause_after"] = False
                for j in _queue:
                    if j["status"] == "queued":
                        j["status"] = "held"
                _persist()
                break
            job = _next_job(_queue, _worker.get("model"))
            if job is None:
                _worker["thread"] = None
                break
            job["project"] = job["params"].get("project") or ""
            job.update(status="running", started=time.time())
        _persist()
        try:
            results = _run_job(job)
            with _lock:  # an interrupted job still returns the images made so far
                job.update(status="done" if job["status"] == "running" else "cancelled", results=results, finished=time.time())
                if job["status"] == "done" and _job_model(job):
                    _worker["model"] = _job_model(job)
                done_any = done_any or bool(results)
            # recorded outside _lock — _remember_speed takes it too and it is not reentrant
            if job["status"] == "done" and results and job.get("started"):
                _remember_speed((job.get("params") or {}).get("backend"), (job["finished"] - job["started"]) / len(results))
        except Exception as e:
            with _lock:
                job.update(status="cancelled" if job["status"] == "cancelling" else "error",
                            error=_error_text(e, (job.get("params") or {}).get("backend") or "forge"), finished=time.time())
            try:
                err_path = os.path.join(os.path.dirname(CFG["queue_file"]), "last-job-error.log") if CFG.get("queue_file") else None
                if err_path:
                    with open(err_path, "w") as f:
                        f.write(f"job {job.get('id')} backend={(job.get('params') or {}).get('backend')}\n")
                        f.write(f"error: {_error_text(e, (job.get('params') or {}).get('backend') or 'forge')}\n")
                        f.write(traceback.format_exc())
            except Exception:
                pass
            # A failed checkpoint switch can leave Forge on either checkpoint; re-read its reported state
            # before choosing which queued job to run next.
            _worker["model"] = _loaded_forge_model()
        _persist()
    _keep_awake(False)
    if done_any and _worker["notify"]:
        with _lock:
            n = sum(len(j["results"]) for j in _queue if j["status"] == "done" and not j.get("notified"))
            for j in _queue:
                j["notified"] = True
        if n:
            try:
                _notify("Spellbook UI", f"{n} image{'s' if n != 1 else ''} ready")
            except Exception:
                pass


def _start_worker():
    with _lock:
        if _worker["thread"] is None:
            _worker["thread"] = threading.Thread(target=_loop, daemon=True)
            _worker["thread"].start()
            _keep_awake(True)


def _keep_awake(on):
    """While the queue runs, `caffeinate -i` stops the Mac idling to sleep (screen can still turn off).
    Non-macOS: no-op — the display sleep policy is left to the OS."""
    if sys.platform != "darwin":
        return
    import subprocess
    p = _worker.get("caffeinate")
    if on and _worker.get("awake", True) and (p is None or p.poll() is not None):
        try:
            _worker["caffeinate"] = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
        except OSError:
            pass
    elif not on and p is not None and p.poll() is None:
        try:
            p.terminate()
            p.wait(timeout=1.0)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
        _worker["caffeinate"] = None


import atexit
atexit.register(lambda: _keep_awake(False))


@router.post("/run")
def run(params: dict = Body(None), jobs: list = Body(None)):
    """One job ({params}) or several ({jobs: [{params, label}]}); all are queued behind any running job."""
    items = jobs if jobs else [{"params": params, "label": ""}]
    backends = {(it.get("params") or {}).get("backend") or "forge" for it in items}
    unknown = backends - {"forge"}
    if unknown:
        raise HTTPException(400, f"Unknown generation engine: {', '.join(sorted(unknown))}")
    added = []
    with _lock:
        for it in items[:200]:
            p = it.get("params") or {}
            _worker["seq"] += 1
            jid = f"j{int(time.time())}-{_worker['seq']}"
            _queue.append({"id": jid, "label": it.get("label") or (p.get("prompt") or "")[:60], "params": p, "status": "queued",
                           "results": [], "error": None, "started": 0.0, "finished": 0.0,
                           "total": max(1, min(int(p.get("count") or 1), 16))})
            added.append(jid)
        # keep the list short: drop old finished jobs
        finished = [j for j in _queue if j["status"] in ("done", "error", "cancelled")]
        for j in finished[:-30]:
            _queue.remove(j)
    _start_worker()
    _persist()
    return {"ok": True, "ids": added}


def _avg_image_seconds(backend=None):
    # Preferred source: recent per-image durations, persisted across sessions
    # (loaded in restore_queue next to queue.json). Falls back to this session's queue.
    if _SPEED.get("forge"):
        vals = _SPEED["forge"]
        return sum(vals) / len(vals)
    pool = [x for v in _SPEED.values() for x in v[-5:]]
    if pool:
        return sum(pool) / len(pool)
    times = [(j["finished"] - j["started"]) / max(1, len(j["results"])) for j in _queue
             if j["status"] == "done" and j["results"]]
    return sum(times[-5:]) / len(times[-5:]) if times else None


_SPEED = {}   # engine "forge" -> recent per-image durations in seconds
_SPEED_FILE = ""


def _load_speed_cache():
    global _SPEED_FILE
    if not CFG.get("queue_file"):
        return
    path = os.path.join(os.path.dirname(CFG["queue_file"]), "speed.json")
    _SPEED_FILE = path
    try:
        with open(path) as f:
            saved = json.load(f)
        for key in ("forge", "krea2"):  # krea2 entries persist but are ignored; the backend was removed
            vals = [float(x) for x in (saved.get(key) or []) if isinstance(x, (int, float)) and x > 0]
            if vals:
                _SPEED[key] = vals[-5:]
    except (OSError, ValueError):
        pass


def _remember_speed(backend, per_image_seconds):
    key = "forge"
    if not per_image_seconds or per_image_seconds <= 0 or per_image_seconds > 24 * 3600:
        return
    with _lock:
        vals = _SPEED.setdefault(key, [])
        vals.append(round(float(per_image_seconds), 1))
        del vals[:-5]
    if not _SPEED_FILE:
        return
    tmp = _SPEED_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(_SPEED, f)
        os.replace(tmp, _SPEED_FILE)
    except OSError:
        pass


@router.get("/progress")
async def progress(preview: bool = True):
    with _lock:
        q = [dict(j) for j in _queue]
    running = next((j for j in q if j["status"] == "running"), None)
    queued = [j for j in q if j["status"] == "queued"]
    avg = _avg_image_seconds()
    out = {"running": running is not None, "queue": [{k: j[k] for k in ("id", "label", "status", "error", "total")} |
                                                    {"results": [r["name"] for r in j["results"]],
                                                     "style": j["params"].get("style", "")} for j in q],
           "left_images": sum(j["total"] for j in queued) + (running["total"] if running else 0),
           "held": sum(1 for j in q if j["status"] == "held"),
           "pause_after": bool(_worker.get("pause_after")),
           "avg_image_seconds": avg,
           "avg_image_seconds_overall": avg}
    if running:
        out.update(id=running["id"], label=running["label"], total=running["total"], elapsed=time.time() - running["started"])
        try:
            skip = "false" if preview else "true"
            p = await _async_call(f"/sdapi/v1/progress?skip_current_image={skip}", timeout=3)
            st = p.get("state") or {}
            out.update(progress=p.get("progress", 0), eta=p.get("eta_relative", 0), step=st.get("sampling_step"),
                       steps=st.get("sampling_steps"), image_no=(st.get("job_no") or 0) + 1)
            if preview and p.get("current_image"):
                out["preview"] = "data:image/png;base64," + p["current_image"]
        except Exception:
            out.update(progress=0)
    return out


@router.post("/cancel")
async def cancel(id: str = Body(None, embed=True)):
    """Cancel one job (queued or running), or everything when id is omitted."""
    stop_running = False
    with _lock:
        for j in _queue:
            if id and j["id"] != id:
                continue
            if j["status"] in ("queued", "held"):
                j["status"] = "cancelled"
            elif j["status"] == "running":
                j["status"] = "cancelling"
                stop_running = True
    if stop_running:
        try:
            await _async_call("/sdapi/v1/interrupt", {})
        except Exception:
            pass
    _persist()
    return {"ok": True}


@router.post("/pause-after")
def set_pause_after(on: bool = Body(..., embed=True)):
    with _lock:
        _worker["pause_after"] = bool(on)
        return {"ok": True, "pause_after": _worker["pause_after"]}


@router.post("/clear")
def clear():
    with _lock:
        _queue[:] = [j for j in _queue if j["status"] in ("queued", "running", "cancelling", "held")]
    _persist()
    return {"ok": True}


@router.post("/reorder")
def reorder(ids: list[str] = Body(..., embed=True)):
    """Reorder pending (queued / held) jobs by an ordered list of IDs."""
    with _lock:
        id_map = {j["id"]: j for j in _queue if j["status"] in ("queued", "held")}
        pending_indices = [i for i, j in enumerate(_queue) if j["status"] in ("queued", "held")]
        reordered = [id_map[jid] for jid in ids if jid in id_map]
        for jid, job in id_map.items():
            if job not in reordered:
                reordered.append(job)
        for idx, job in zip(pending_indices, reordered):
            _queue[idx] = job
    _persist()
    return {"ok": True}


@router.post("/notify")
def set_notify(on: bool = Body(None), awake: bool = Body(None)):
    if on is not None:
        _worker["notify"] = bool(on)
    if awake is not None:
        _worker["awake"] = bool(awake)
    return {"ok": True}


@router.post("/interrupt")
async def interrupt():
    try:
        await _async_call("/sdapi/v1/interrupt", {})
    except Exception as e:
        return {"ok": False, "error": _offline(e)}
    return {"ok": True}


_NAME = re.compile(r"^\d{8}-\d{6}-\d+\.png$")
_history_cache = {"sig": None, "data": None}


def _path(name):
    if not _NAME.match(name or ""):
        raise HTTPException(400, "Bad name")
    p = os.path.join(CFG["out_dir"], name)
    if not os.path.exists(p):
        raise HTTPException(404, "Not found")
    return p


@router.get("/compare/{cid}")
def compare(cid: str):
    """One comparison batch (jobs queued together, tagged params.compare.id): finished images plus jobs still to run."""
    items = []
    try:
        names = [n for n in os.listdir(CFG["out_dir"]) if n.endswith(".json")]
    except OSError:
        names = []
    for n in names:
        try:
            with open(os.path.join(CFG["out_dir"], n)) as f:
                m = json.load(f)
        except (OSError, ValueError):
            continue
        if ((m.get("params") or {}).get("compare") or {}).get("id") == cid and m.get("params", {}).get("mode") not in ("fix", "upscale"):
            items.append(m)
    with _lock:
        pending = [{"job": j["id"], "status": j["status"], "params": j["params"], "label": j["label"]} for j in _queue
                   if ((j["params"].get("compare") or {}).get("id") == cid) and j["status"] in ("queued", "running", "held")]
    items.sort(key=lambda m: m.get("time", 0))
    return {"id": cid, "items": items, "pending": pending}


@router.get("/history")
def history(limit: int = 200):
    out_dir = CFG["out_dir"]
    try:
        names = sorted((n for n in os.listdir(out_dir) if n.endswith(".json")), reverse=True)[:limit]
    except OSError:
        return []
    sig = []
    for n in names:
        p = os.path.join(out_dir, n)
        try:
            st = os.stat(p)
            sig.append((n, st.st_mtime_ns, st.st_size))
        except OSError:
            sig.append((n, 0, 0))
    key = (out_dir, limit, tuple(sig))
    if _history_cache["sig"] == key:
        return _history_cache["data"]
    out = []
    for n in names:
        try:
            with open(os.path.join(out_dir, n)) as f:
                data = json.load(f)
                # unexpected sidecar types would crash the UI
                if isinstance(data, dict):
                    out.append(data)
        except (OSError, ValueError):
            pass
    _history_cache["sig"] = key
    _history_cache["data"] = out
    return out


@router.get("/image/{name}")
def image(name: str):
    return FileResponse(_path(name), headers={"Cache-Control": "max-age=604800"})


@router.get("/thumb/{name}")
def thumb(name: str):
    """Small JPEG of a gallery image (pose browser reference pictures), cached in a hidden folder."""
    src = _path(name)
    d = os.path.join(CFG["out_dir"], ".thumbs")
    out = os.path.join(d, name[:-4] + ".jpg")
    if not os.path.exists(out) or os.path.getmtime(out) < os.path.getmtime(src):
        from PIL import Image
        os.makedirs(d, exist_ok=True)
        with Image.open(src) as im:
            im = im.convert("RGB")
            im.thumbnail((320, 480))
            im.save(out, quality=92)
    return FileResponse(out, headers={"Cache-Control": "max-age=604800"})


@router.post("/delete")
def delete(name: str = Body(None), names: list = Body(None)):
    for n in (names or [name]):
        p = _path(n)
        for f in (p, p[:-4] + ".json"):
            try:
                os.remove(f)
            except OSError:
                pass
    # Invalidate history cache because the sidecar file(s) changed
    _history_cache["sig"] = None
    return {"ok": True}


@router.post("/star")
def star(names: list = Body(...), on: bool = Body(True)):
    for n in names:
        meta_path = _path(n)[:-4] + ".json"
        try:
            with open(meta_path) as f:
                meta = json.load(f)
            meta["starred"] = bool(on)
            with open(meta_path, "w") as f:
                json.dump(meta, f)
            # Invalidate history cache because the sidecar file changed
            _history_cache["sig"] = None
        except (OSError, ValueError):
            pass
    return {"ok": True}




@router.post("/export")
def export(names: list = Body(..., embed=True)):
    """Copy images (with their prompt in a .txt beside each) to the export folder (Settings) and show the folder."""
    import shutil
    import subprocess
    os.makedirs(CFG["export_dir"], exist_ok=True)
    for n in names:
        src = _path(n)
        shutil.copy2(src, os.path.join(CFG["export_dir"], n))
        try:
            with open(src[:-4] + ".json") as f:
                meta = json.load(f)
            with open(os.path.join(CFG["export_dir"], n[:-4] + ".txt"), "w") as f:
                f.write(meta.get("infotext") or meta.get("final_prompt") or "")
        except (OSError, ValueError):
            pass
    subprocess.run(["open", CFG["export_dir"]], check=False)
    return {"ok": True, "folder": CFG["export_dir"], "count": len(names)}


@router.post("/reveal")
def reveal(name: str = Body(..., embed=True)):
    import subprocess
    subprocess.run(["open", "-R", _path(name)], check=False)
    return {"ok": True}
