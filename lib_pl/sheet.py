"""Character reference sheet builder: one generation per pose (OpenPose skeleton from posekit) and per expression,
then a labeled grid. Talks to Forge's own HTTP API (Forge must run with --api)."""
import base64
import io
import json
import os
import sys
import re
import urllib.request

from PIL import Image, ImageDraw, ImageFont

from .presets import merge_csv

# posekit is vendored here: the skeleton builder for the pose panels,
# bundled so a fresh clone runs standalone. Only stdlib + Pillow; no other consumers import it.
POSEKIT_DIR = os.path.dirname(os.path.abspath(__file__))
OPENPOSE = "xinsir_openpose_sdxl [d0333a45]"  # control-lora was overpowered by the style LoRAs (2026-10-18 test)
IPADAPTER = ("CLIP-ViT-H (IPAdapter)", "ip-adapter-plus_sdxl_vit-h [bc449f62]")

# label -> (posekit preset, extra tags). BACK_POSES skip posekit's own tags and the IP-Adapter reference.
POSES = {
    "DASH": ("dash", "running"),
    "AIRBORNE": ("leap_joy", "jumping, midair"),
    "LANDING": ("landing_adult", "superhero landing, (kneeling:1.2), one knee, fist on ground, looking ahead"),  # hero_landing is tuned for chibi proportions (blob legs at 6.5 heads)
    "DEFIANT": ("pinup_contrapposto", "hand on hip, confident"),
    "STARTLED RECOIL": ("startled_recoil", "surprised"),
    "JOYFUL VICTORY": ("victory_fist", "happy, grin"),
    "SIDE VIEW": ("pinup_side", "from side, profile"),
    "BACK VIEW": ("pinup_back", "(from behind:1.4), (back:1.3), facing away, back of head, standing, hand on hip"),
    "3/4 BACK": ("look_back_guard", "(from behind:1.3), back, looking back, looking over shoulder, profile, standing"),
}
NO_KIT_TAGS = {"BACK VIEW", "3/4 BACK", "LANDING"}  # posekit tags 'dust, impact' added ground/scenery to LANDING
# The reference panel is always front-facing: with IP-Adapter on, back views came out frontal (Jinx run 2026-10-18).
BACK_POSES = {"BACK VIEW", "3/4 BACK"}
FRONT_ONLY = re.compile(r"\b(navel|midriff|cleavage|breasts|collarbone|abs|stomach)\b")
BACK_NEG = "(looking at viewer:1.2), facing viewer, front view, navel, cleavage, breasts"
# Colour from pink/red eyes, clothes and eyeshadow bled into the skin (Jinx run).
SKIN_NEG = "pink skin, colored skin, red skin, purple skin, sunburn, scenery, ground, landscape, rocks"
BUST_NEG = ("full body, legs, thighs, hips, knees, knee up, crouching, squatting, kicking, cowboy shot, multiple views, "
            "chibi, hand on own face, hand on own chin, hand to own mouth, hand on own cheek, hand up, v, peace sign, "
            "hands, fingers, waving, pointing, fist, navel, midriff, stomach, hands on hips")
EXPRESSIONS = {
    "NEUTRAL": "closed mouth, light smile, calm",
    "JOY": "laughing, closed eyes, open mouth, happy, blush",
    "ANGER": "angry, v-shaped eyebrows, clenched teeth, glaring",
    "SHOCK": "surprised, wide-eyed, open mouth, shocked",
    "SADNESS": "sad, tears, frown, downcast eyes",
    "DETERMINATION": "determined, serious, furrowed brow, closed mouth",
    "EMBARRASSMENT": "embarrassed, blush, wavy mouth, looking away, sweatdrop",
    "MISCHIEF": "one eye closed, smirk, mischievous, tongue out",
}
BUST = "bust"  # head-and-shoulders skeleton filling the frame (prompt alone gave full bodies)
BODY_LORA = re.compile(r"<lora:fsthicc[^>]*>\s*,?\s*")  # body-shape LoRA fights head shots
POSE_SIZE = (832, 1216)
FACE_SIZE = (1024, 1024)


COLOR_TAG = re.compile(r"^(?:[a-z]+ )?(?:blonde|black|white|red|blue|green|pink|purple|brown|orange|grey|gray|silver|aqua|yellow)"
                       r"(?:[- ][a-z]+)? hair$")  # hair only: weighting eye colour spread pink eyes into the skin


LOWER_BODY = re.compile(r"\b(shoes?|footwear|sneakers?|boots?|heels|sandals|socks?|kneehighs|thighhighs|pantyhose|"
                        r"legwear|stockings|leggings|shorts|skirt|miniskirt|pants|jeans|garter\w*|barefoot|thighs?|legs?|feet)\b")


def upper_only(character):
    """Busts: lower-body clothing tags pull legs and feet into the frame (crouching busts in the 2026-10-18 test)."""
    return ", ".join(t.strip() for t in character.split(",") if t.strip() and not LOWER_BODY.search(t))


def head_only(character):
    """Busts: no lower-body or torso tags (navel/midriff framed busts waist-up with a pink belly blob)."""
    return ", ".join(t for t in (t.strip() for t in upper_only(character).split(",")) if t and not FRONT_ONLY.search(t))


def weight_colors(character, w=1.2):
    """Hair colour tags get extra weight: expression tags ('angry') otherwise recolour them (red hair on ANGER)."""
    out = []
    for t in (t.strip() for t in character.split(",")):
        if t:
            out.append(f"({t}:{w})" if COLOR_TAG.match(t) else t)
    return ", ".join(out)


def build_jobs(character, preset, poses, expressions):
    """Pure: the list of panel generations. `character` = comma tags from the interrogator."""
    character = weight_colors(character)
    cfg = preset.sheet or {}
    prefix, suffix = cfg.get("panel_prefix", ""), cfg.get("panel_suffix", "")
    neg = merge_csv(preset.negative, cfg.get("panel_negative_extra", ""), SKIN_NEG)
    tags = _posekit().PRESETS
    jobs = []
    for label in poses:
        name, extra = POSES[label]
        back = label in BACK_POSES
        char = ", ".join(t.strip() for t in character.split(",") if t.strip() and not FRONT_ONLY.search(t)) if back else character
        jobs.append(dict(label=label, kind="pose", pose=name, size=POSE_SIZE, ip=not back,
                         negative=merge_csv(neg, BACK_NEG) if back else neg,
                         prompt=merge_csv(prefix, char, extra, "" if label in NO_KIT_TAGS else tags[name]["tags"], suffix,
                                          "solo, full body, white background, simple background")))
    for label in expressions:
        jobs.append(dict(label=label, kind="face", pose=BUST, size=FACE_SIZE, ip=True, negative=merge_csv(neg, BUST_NEG),
                         prompt=merge_csv(BODY_LORA.sub("", prefix).strip(", "), head_only(character), EXPRESSIONS[label],
                                          "solo, portrait, headshot, head and shoulders, close-up, looking at viewer, arms down, "
                                          "white background, simple background")))
    return jobs


def _posekit():
    if POSEKIT_DIR not in sys.path:
        sys.path.insert(0, POSEKIT_DIR)
    import posekit
    return posekit

def skeleton(name, heads, size):
    if name == BUST:  # head and shoulders only: hip/leg lines read as a raised knee, arm lines as hands at the face
        pk = _posekit()
        pts, pelvis, _ = pk.build(pk.PRESETS["pinup_contrapposto"], heads)
        scale = 0.42 * heads  # 0.30 framed busts waist-up (Jinx run)
        placed, ph, _ = pk.place(pts, heads, size[0], size[1], scale, (0.5, 0.06 + scale / 2), False)
        return pk.draw({k: v for k, v in placed.items() if k not in (3, 4, 6, 7, 8, 9, 10, 11, 12, 13)}, size[0], size[1], ph)
    img, _ = _posekit().render(name, heads, size[0], size[1], size=0.72, quiet=True)
    return img


def _b64(img):
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def payload(job, settings, seed, heads, ref=None, ref_weight=0.4):
    w, h = job["size"]
    p = {"prompt": job["prompt"], "negative_prompt": job["negative"], "seed": seed, "width": w, "height": h,
         "steps": settings["steps"], "sampler_name": settings["sampler"], "cfg_scale": settings["cfg"],
         "override_settings": {"CLIP_stop_at_last_layers": settings.get("clip_skip", 2)}}
    if settings.get("scheduler"):
        p["scheduler"] = settings["scheduler"]
    if settings.get("checkpoint"):
        p["override_settings"]["sd_model_checkpoint"] = settings["checkpoint"]
    units = []
    if ref is not None and job.get("ip", True):
        if job["kind"] == "face":  # busts: reference the head, not the whole body
            ref = trim(ref)
            ref = ref.crop((0, 0, ref.width, min(ref.height, int(ref.width * 0.75))))  # head/shoulders: legs in ref -> legs in bust
        # pose panels: start IP-Adapter after the skeleton has set the pose, or it copies the ref's pose (back view came out frontal)
        units.append({"enabled": True, "module": IPADAPTER[0], "model": IPADAPTER[1], "image": _b64(ref),
                      "weight": ref_weight if job["kind"] == "pose" else min(ref_weight, 0.3), "guidance_start": 0.4 if job["kind"] == "pose" else 0.25, "guidance_end": 0.9})
    if job["pose"]:
        units.append({"enabled": True, "module": "None", "model": OPENPOSE, "image": _b64(skeleton(job["pose"], heads, job["size"])),
                      "weight": 1.0, "guidance_start": 0.0, "guidance_end": 0.9, "resize_mode": "Just Resize"})
    if units:
        p["alwayson_scripts"] = {"controlnet": {"args": units}}
    return p


def generate(api, body, timeout=900):
    req = urllib.request.Request(f"{api.rstrip('/')}/sdapi/v1/txt2img", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    return Image.open(io.BytesIO(base64.b64decode(data["images"][0]))).convert("RGB")


# ---------------------------------------------------------------- layout

def trim(img, pad=12, thresh=238):
    """Crop to the non-white content."""
    mask = img.convert("L").point(lambda v: 255 if v < thresh else 0)
    box = mask.getbbox()
    if not box:
        return img
    l, t, r, b = box
    return img.crop((max(0, l - pad), max(0, t - pad), min(img.width, r + pad), min(img.height, b + pad)))


def _font(size):
    for path in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/Helvetica.ttc"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit(img, w, h):
    s = min(w / img.width, h / img.height)
    return img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))), Image.LANCZOS)


def bust_crop(img):
    """Head and shoulders from a waist-up bust. Nova ignores head size in a face-only skeleton and frames busts at the
    waist (Jinx run), so the sheet crops instead: a square-ish box under the top of the hair, ~60% of the width tall."""
    w = img.width
    side = int(w * 0.78)
    left = (w - side) // 2
    return img.crop((left, 0, left + side, min(img.height, int(side * 0.95))))


def compose(panels, width=2400, pose_cols=3, face_cols=8, bg=(255, 255, 255)):
    """panels: [(label, kind, image)] in order. Poses in rows of `pose_cols`, then expression busts in rows of `face_cols`."""
    poses = [p for p in panels if p[1] == "pose"]
    faces = [p for p in panels if p[1] == "face"]
    pw, ph, lab = width // pose_cols, int(width // pose_cols * 1.25), 56
    fw = width // face_cols
    fh = int(fw * 1.1)
    prow = -(-len(poses) // pose_cols)
    frow = -(-len(faces) // face_cols)
    H = prow * (ph + lab) + frow * (fh + lab // 2 + 10) + 40
    sheet = Image.new("RGB", (width, max(H, 100)), bg)
    dr = ImageDraw.Draw(sheet)
    big, small = _font(30), _font(max(16, fw // 12))
    for i, (label, _, img) in enumerate(poses):
        x, y = (i % pose_cols) * pw, (i // pose_cols) * (ph + lab)
        dr.text((x + 30, y + 20), label, fill=(20, 20, 20), font=big)
        fig = _fit(trim(img), pw - 60, ph - 20)
        sheet.paste(fig, (x + (pw - fig.width) // 2, y + lab + (ph - fig.height) // 2))
    top = prow * (ph + lab) + 20
    for i, (label, _, img) in enumerate(faces):
        x, y = (i % face_cols) * fw, top + (i // face_cols) * (fh + lab // 2 + 10)
        dr.text((x + 12, y), label, fill=(20, 20, 20), font=small)
        t = trim(img)
        t = bust_crop(t)
        fig = _fit(t, fw - 16, fh - 10)
        sheet.paste(fig, (x + (fw - fig.width) // 2, y + lab // 2 + 10 + (fh - fig.height)))
    return sheet


def run(api, jobs, settings, seed, heads, out_dir, ref_weight=0.4, gen=generate):
    """Generator: yields (done, total, label, path) after each panel, then (total, total, 'SHEET', sheet_path).
    The first panel becomes the IP-Adapter reference for the rest so outfit and face stay consistent."""
    os.makedirs(out_dir, exist_ok=True)
    panels, ref = [], None
    for i, job in enumerate(jobs):
        img = gen(api, payload(job, settings, seed, heads, ref, ref_weight))
        if ref is None:
            ref = img
        path = os.path.join(out_dir, f"{i + 1:02d}_{job['label'].lower().replace('/', '-').replace(' ', '_')}.png")
        img.save(path)
        panels.append((job["label"], job["kind"], img))
        yield i + 1, len(jobs), job["label"], path
    path = os.path.join(out_dir, "sheet.png")
    compose(panels).save(path)
    with open(os.path.join(out_dir, "sheet.json"), "w") as f:
        json.dump({"seed": seed, "heads": heads, "jobs": [{k: v for k, v in j.items() if k != "size"} for j in jobs]}, f, indent=1)
    yield len(jobs), len(jobs), "SHEET", path
