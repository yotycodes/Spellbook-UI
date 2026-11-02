"""Read joints out of OpenPose skeleton images and tag them, so 9,000+ unnamed poses become searchable.

OpenPose (controlnet_aux draw_bodypose) draws 17 limbs, each in its own hue 20 degrees apart. Hue survives JPEG
and anti-aliasing better than the joint dots, so each limb's pixels are found by hue, a principal axis gives its two
end points, and joints are chained outward from the neck. From the joints come posture/arm/leg/view tags and a
normalized vector used for "find similar poses".

usage: python -I pose_features.py <packs dir>      -> writes <packs dir>/features.json
       python -I pose_features.py --one <image>    -> prints tags for one image (debug)"""
import json
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor

import numpy as np
from PIL import Image

# COCO-18 keypoints
NOSE, NECK, RSHO, RELB, RWRI, LSHO, LELB, LWRI, RHIP, RKNE, RANK, LHIP, LKNE, LANK, REYE, LEYE, REAR, LEAR = range(18)
# limb i -> (from, to), drawn in hue i*20 degrees (controlnet_aux limbSeq order)
LIMBS = [(NECK, RSHO), (NECK, LSHO), (RSHO, RELB), (RELB, RWRI), (LSHO, LELB), (LELB, LWRI), (NECK, RHIP), (RHIP, RKNE),
         (RKNE, RANK), (NECK, LHIP), (LHIP, LKNE), (LKNE, LANK), (NECK, NOSE), (NOSE, REYE), (REYE, REAR), (NOSE, LEYE),
         (LEYE, LEAR)]
HUES = [i * 20 for i in range(17)]


def _hsv(a):
    a = a.astype(np.float32) / 255.0
    mx, mn = a.max(2), a.min(2)
    d = mx - mn + 1e-6
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    h = np.where(mx == r, (g - b) / d % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) * 60
    return h, d / (mx + 1e-6), mx


def _segment(pts):
    """Two end points of a limb from its pixel cloud (principal axis, trimmed extremes)."""
    c = pts.mean(0)
    u, s, vt = np.linalg.svd(pts - c, full_matrices=False)
    ax = vt[0]
    t = (pts - c) @ ax
    lo, hi = np.percentile(t, 3), np.percentile(t, 97)
    return c + ax * lo, c + ax * hi


def _people(xs, width):
    """How many people: count clusters of the neck-to-nose limb along x."""
    if len(xs) < 4:
        return 1
    xs = np.sort(xs)
    return 1 + int((np.diff(xs) > width * 0.12).sum())


def _erode(m, r=1):
    """Binary erosion with a (2r+1)^2 square: thin hand/face strokes vanish, thick limb strokes survive."""
    out = m.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            out &= np.roll(np.roll(m, dy, 0), dx, 1)
    return out


def _components(mask):
    """Connected pieces (8-neighbour) of a small boolean mask, largest first, as (ys, xs) arrays."""
    ys, xs = np.nonzero(mask)
    left = set(zip(ys.tolist(), xs.tolist()))
    comps = []
    while left:
        seed = left.pop()
        stack, comp = [seed], [seed]
        while stack:
            y, x = stack.pop()
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    q = (y + dy, x + dx)
                    if q in left:
                        left.remove(q)
                        stack.append(q)
                        comp.append(q)
        comps.append(comp)
    comps.sort(key=len, reverse=True)
    return [np.array(c) for c in comps]


def keypoints(path, max_side=384):
    im = Image.open(path).convert("RGB")
    im.thumbnail((max_side, max_side))
    a = np.asarray(im)
    h, s, v = _hsv(a)
    on = (v > 0.22) & (s > 0.5)
    thick = _erode(on, 1)
    segs, people = {}, 1
    for i, hh in enumerate(HUES):
        dh = np.abs(((h - hh) + 180) % 360 - 180)
        face = i >= 13                                      # eye/ear strokes are short: no erosion, smaller minimum
        m = (on if face else thick) & (dh < 8)
        if m.sum() < (3 if face else 6):
            continue
        comps = [c for c in _components(m) if len(c) >= (3 if face else 6)]
        if not comps:
            continue
        if i == 0:   # neck->right-shoulder is long and thick: one solid piece per person
            people = max(1, sum(1 for c in comps if len(c) >= 0.6 * len(comps[0]) and len(c) >= 25))
        pts = comps[0][:, ::-1].astype(np.float32)          # (x, y) of the largest piece of this limb colour
        segs[i] = _segment(pts)
    kp = [None] * 18
    # neck: the end point shared by the limbs that leave it
    neck_limbs = [i for i in (0, 1, 6, 9, 12) if i in segs]
    if len(neck_limbs) >= 2:
        cands = [p for i in neck_limbs for p in segs[i]]
        best = min(cands, key=lambda p: sum(min(np.linalg.norm(p - a_), np.linalg.norm(p - b_)) for a_, b_ in (segs[i] for i in neck_limbs)))
        kp[NECK] = best
    elif len(neck_limbs) == 1:
        return None, people, im.size
    else:
        return None, people, im.size
    # walk outward: for each limb, the end nearer its known joint is that joint, the other is the next one
    for _ in range(3):
        for i, (a_, b_) in enumerate(LIMBS):
            if i not in segs or kp[a_] is None or kp[b_] is not None:
                continue
            p, q = segs[i]
            near, far = (p, q) if np.linalg.norm(p - kp[a_]) <= np.linalg.norm(q - kp[a_]) else (q, p)
            kp[b_] = far
    if kp[NOSE] is None:
        # turned away: no face strokes, but the ears are still drawn as lone dots (keypoint hues 320 and 340)
        for j, hh in ((REAR, 320), (LEAR, 340)):
            dh = np.abs(((h - hh) + 180) % 360 - 180)
            comps = [c for c in _components(on & (dh < 8)) if len(c) >= 3]
            above = [c for c in comps if c[:, 0].mean() < kp[NECK][1]]
            if above:
                c = max(above, key=len)
                kp[j] = np.array([c[:, 1].mean(), c[:, 0].mean()], dtype=np.float32)
    return kp, people, im.size


def _ang(v):
    return math.degrees(math.atan2(v[1], v[0]))


def tags_for(kp, people, size):
    t = set()
    if people > 1:
        t.add("group")
    if kp is None or kp[NECK] is None:
        return sorted(t)
    P = lambda i: kp[i]
    have = lambda *ii: all(kp[i] is not None for i in ii)
    hips = [i for i in (RHIP, LHIP) if kp[i] is not None]
    if not hips:
        t.add("close-up" if kp[NOSE] is not None else "upper body")
        return sorted(t)
    mid_hip = np.mean([kp[i] for i in hips], 0)
    torso = np.linalg.norm(mid_hip - kp[NECK]) or 1.0
    tv = mid_hip - kp[NECK]                                   # neck -> hips
    tilt = abs(90 - abs(_ang(tv)))                            # 0 = upright torso
    # view
    eyes = [kp[i] is not None for i in (REYE, LEYE)]
    ears = [kp[i] is not None for i in (REAR, LEAR)]
    # Body facing comes from shoulder order (OpenPose labels sides by anatomy: facing the viewer, the right shoulder
    # is on the image's left); a face drawn on a back view means looking back over the shoulder. A head with no face
    # (ear dots only) is turned away. No head at all (cropped) says nothing about the view.
    body = "front"
    if kp[RSHO] is not None and kp[LSHO] is not None:
        d = (kp[LSHO][0] - kp[RSHO][0]) / torso
        body = "back" if d < -0.15 else "side" if abs(d) < 0.15 else "front"
    if kp[NOSE] is None:
        if any(ears) or any(eyes) or body == "back":
            t.add("from behind")
    elif body == "back":
        t.update(("from behind", "looking back"))
    elif sum(eyes) == 1 or (sum(ears) == 1 and sum(eyes) < 2):
        t.add("from side")
    else:
        t.add("front view")
    # framing
    if any(kp[i] is not None for i in (RANK, LANK)):
        t.add("full body")
    elif any(kp[i] is not None for i in (RKNE, LKNE)):
        t.add("cowboy shot")
    else:
        t.add("upper body")
    # posture (needs legs)
    def leg(h_, k_, a_):
        if not have(h_, k_):
            return None
        th = P(k_) - P(h_)
        thigh_down = th[1] / (np.linalg.norm(th) + 1e-6)          # 1 = straight down
        shin_down = None
        if kp[a_] is not None:
            sh = P(a_) - P(k_)
            shin_down = sh[1] / (np.linalg.norm(sh) + 1e-6)
        return thigh_down, shin_down
    legs = [l for l in (leg(RHIP, RKNE, RANK), leg(LHIP, LKNE, LANK)) if l]
    if tilt > 55:
        t.add("lying")
        if any(kp[i] is not None and kp[i][1] > kp[NECK][1] + 0.3 * torso for i in (RWRI, LWRI)) and legs and any(abs(l[0]) < 0.6 for l in legs):
            t.add("all fours")
    elif legs:
        th = [l[0] for l in legs]
        sh = [l[1] for l in legs if l[1] is not None]
        knees = [kp[i][1] for i in (RKNE, LKNE) if kp[i] is not None]
        hip_knee = (np.mean(knees) - mid_hip[1]) / torso if knees else 1.0   # how far the knees sit below the hips
        if all(x > 0.75 for x in th) and (not sh or all(x > 0.6 for x in sh)):
            t.add("standing")
        elif all(x > 0.65 for x in th) and sh and all(abs(x) < 0.55 for x in sh):
            t.add("kneeling")
        elif all(abs(x) < 0.6 for x in th) and sh and any(x > 0.6 for x in sh) and hip_knee < 0.45 and tilt < 30:
            knee_y = np.mean([kp[i][1] for i in (RKNE, LKNE) if kp[i] is not None])
            ank = [kp[i][1] for i in (RANK, LANK) if kp[i] is not None]
            if ank and (np.mean(ank) - mid_hip[1]) < 0.55 * torso:
                t.add("squatting")
            else:
                t.add("sitting")
        elif all(x < 0.35 for x in th) and hip_knee < 0.45:
            t.add("sitting")
        elif any(x > 0.8 for x in th) and any(abs(x) < 0.45 for x in th):
            t.add("leg up")   # one leg straight down, the other lifted: kick, step, run
    if 20 < tilt <= 55 and "lying" not in t:
        t.add("leaning")
    # arms
    shoulder = {RWRI: RSHO, LWRI: LSHO}
    up = [w for w in (RWRI, LWRI) if have(w, shoulder[w]) and P(w)[1] < P(shoulder[w])[1] - 0.25 * torso]
    if len(up) == 2:
        t.add("arms up")
    elif len(up) == 1:
        t.add("arm up")
    hipof = {RWRI: RHIP, LWRI: LHIP}
    if all(have(w, hipof[w]) and np.linalg.norm(P(w) - P(hipof[w])) < 0.35 * torso for w in (RWRI, LWRI)):
        t.add("hands on hips")
    elif any(have(w, hipof[w]) and np.linalg.norm(P(w) - P(hipof[w])) < 0.3 * torso for w in (RWRI, LWRI)):
        t.add("hand on hip")
    if have(RWRI, LWRI, RSHO, LSHO):
        mx = (P(RSHO)[0] + P(LSHO)[0]) / 2
        r_side, l_side = np.sign(P(RSHO)[0] - mx), np.sign(P(LSHO)[0] - mx)
        chest = kp[NECK][1] < P(RWRI)[1] < mid_hip[1] and kp[NECK][1] < P(LWRI)[1] < mid_hip[1]
        if chest and np.sign(P(RWRI)[0] - mx) == l_side and np.sign(P(LWRI)[0] - mx) == r_side:
            t.add("crossed arms")
        sw = abs(P(RSHO)[0] - P(LSHO)[0]) or 1
        if all(abs(P(w)[0] - mx) > 1.6 * sw and abs(P(w)[1] - P(shoulder[w])[1]) < 0.35 * torso for w in (RWRI, LWRI)):
            t.add("arms out")
    if kp[NOSE] is not None and any(kp[w] is not None and P(w)[1] < kp[NECK][1] and np.linalg.norm(P(w) - P(NOSE)) < 0.3 * torso for w in (RWRI, LWRI)):
        t.add("hand on face")
    if kp[NOSE] is not None and any(kp[w] is not None and P(w)[1] < P(NOSE)[1] and np.linalg.norm(P(w) - P(NOSE)) < 0.5 * torso for w in (RWRI, LWRI)):
        t.add("hand on head")
    # legs
    if have(RANK, LANK, RHIP, LHIP):
        hw = abs(P(RHIP)[0] - P(LHIP)[0]) or 1
        if "standing" in t and abs(P(RANK)[0] - P(LANK)[0]) > 2.2 * hw:
            t.add("wide stance")
        if np.sign(P(RANK)[0] - P(LANK)[0]) != np.sign(P(RHIP)[0] - P(LHIP)[0]) and abs(P(RANK)[0] - P(LANK)[0]) > 0.3 * hw:
            t.add("crossed legs")
        if abs(P(RANK)[1] - P(LANK)[1]) > 0.55 * torso and "lying" not in t and "sitting" not in t:
            t.add("leg up")
    if ("leg up" in t and "standing" not in t) or (tilt > 25 and "lying" not in t) or ("arms out" in t and "leaning" in t):
        t.add("dynamic")
    return sorted(t)


def vector(kp):
    """Joints relative to the neck, scaled by torso length; None where missing (for similarity)."""
    if kp is None or kp[NECK] is None:
        return None
    hips = [kp[i] for i in (RHIP, LHIP) if kp[i] is not None]
    ref = np.mean(hips, 0) if hips else None
    scale = np.linalg.norm(ref - kp[NECK]) if ref is not None else None
    if not scale:
        sh = [kp[i] for i in (RSHO, LSHO) if kp[i] is not None]
        scale = (np.linalg.norm(sh[0] - sh[1]) * 1.6) if len(sh) == 2 else None
    if not scale:
        return None
    return [None if p is None else [round(float((p[0] - kp[NECK][0]) / scale), 3), round(float((p[1] - kp[NECK][1]) / scale), 3)] for p in kp]


# pose tag -> prompt tags that tell the model the same thing the skeleton does
PROMPT_TAGS = {"standing": "standing", "sitting": "sitting", "kneeling": "kneeling", "lying": "lying", "squatting": "squatting",
               "all fours": "all fours", "arms up": "arms up", "arm up": "arm up", "hands on hips": "hands on own hips",
               "hand on hip": "hand on own hip", "crossed arms": "crossed arms", "arms out": "outstretched arms",
               "hand on face": "hand on own face", "hand on head": "hand on own head", "crossed legs": "crossed legs",
               "wide stance": "legs apart", "leg up": "leg up", "from behind": "from behind", "from side": "from side",
               "looking back": "looking back", "full body": "full body", "cowboy shot": "cowboy shot", "upper body": "upper body", "dynamic": "dynamic pose"}


def prompt_tags(tags):
    return ", ".join(PROMPT_TAGS[t] for t in tags if t in PROMPT_TAGS)


def similar(query, vectors, limit=60):
    """Rank pose vectors by joint distance to `query` (both from vector()). vectors: list of (id, vec).
    Distance = mean gap over shared joints + 0.6 per joint present in only one of the two."""
    q = np.array([[np.nan, np.nan] if p is None else p for p in query], dtype=np.float32)
    ids = [i for i, v in vectors if v is not None]
    if not ids:
        return []
    V = np.array([[[np.nan, np.nan] if p is None else p for p in v] for _, v in vectors if v is not None], dtype=np.float32)
    qm, vm = ~np.isnan(q[:, 0]), ~np.isnan(V[:, :, 0])
    both = vm & qm
    d = np.linalg.norm(np.nan_to_num(V) - np.nan_to_num(q), axis=2)
    shared = both.sum(1)
    mean = np.where(shared > 0, (d * both).sum(1) / np.maximum(shared, 1), 9.0)
    score = mean + 0.6 * (vm ^ qm).sum(1) / 18 * 3
    order = np.argsort(score)[:limit]
    return [(ids[k], float(score[k])) for k in order]


# shoulders to ankles: the neck is the origin, and the nose is skipped (skeletons drawn with hands put blue hand
# dots where the neck->nose stroke's hue is, so it is often misread)
BODY = [RSHO, RELB, RWRI, LSHO, LELB, LWRI, RHIP, RKNE, RANK, LHIP, LKNE, LANK]
SWAP = [NOSE, NECK, LSHO, LELB, LWRI, RSHO, RELB, RWRI, LHIP, LKNE, LANK, RHIP, RKNE, RANK, LEYE, REYE, LEAR, REAR]


# each body joint's limb runs from its parent joint (hips hang from the neck, so they carry the torso's lean)
PARENT = {RSHO: NECK, RELB: RSHO, RWRI: RELB, LSHO: NECK, LELB: LSHO, LWRI: LELB,
          RHIP: NECK, RKNE: RHIP, RANK: RKNE, LHIP: NECK, LKNE: LHIP, LANK: LKNE}
# arms and legs pick their left/right labels separately: on back views DWPose often swaps one pair and not the other
GROUPS = [[RSHO, RELB, RWRI, LSHO, LELB, LWRI], [RHIP, RKNE, RANK, LHIP, LKNE, LANK]]


def _limb(v, j):
    """Direction of joint j's limb, from its nearest present ancestor (a missing elbow -> shoulder to wrist)."""
    if v[j] is None:
        return None
    p = PARENT[j]
    while p is not None and v[p] is None:
        p = PARENT.get(p)
    if p is None or v[p] is None:
        return None
    dx, dy = v[j][0] - v[p][0], v[j][1] - v[p][1]
    return (math.atan2(dy, dx), p) if dx or dy else None


def match(target, result, tol=30):
    """How well a generated pose follows the skeleton, 0-100: the share of the target's limbs (shoulders to ankles)
    that the result points the same way, within `tol` degrees. Limb angles, not joint positions, so a style's body
    proportions (long torso, short legs, curvy hips) don't count against a correct pose. Both are vector() outputs.
    A limb the target has but the result lacks is a miss. Left/right labels are tried both ways per arm pair and leg
    pair (skeleton tools and DWPose disagree on which side is "right"; the shape is what counts). None when the target
    has too few joints to judge."""
    if not target or not result:
        return None
    have = [i for i in BODY if target[i] is not None]
    if len(have) < 4:
        return None

    def hits(t, joints):
        n = 0
        for j in joints:
            a, b = _limb(t, j), _limb(result, j)
            if a and b and a[1] == b[1]:
                d = abs(a[0] - b[0]) % (2 * math.pi)
                n += min(d, 2 * math.pi - d) <= math.radians(tol)
        return n
    swapped = [target[j] for j in SWAP]
    hit = sum(max(hits(target, [j for j in g if j in have]), hits(swapped, [j for j in g if swapped[j] is not None]))
              for g in GROUPS)
    return round(100 * min(hit, len(have)) / len(have))


def expected_facing(tags):
    """Which way the skeleton means the body to face (from its view tag): "back", "front", or None (side/unknown)."""
    tags = tags or []
    return "back" if "from behind" in tags else "front" if "front view" in tags else None


def facing(vec, margin=0.15):
    """Which way a detected body faces, from shoulder order: facing the viewer, the right shoulder is on the image's
    left. DWPose labels sides by anatomy, so a back view flips the order. None when the shoulders are too close
    together to tell (side views)."""
    if not vec or vec[RSHO] is None or vec[LSHO] is None:
        return None
    d = vec[LSHO][0] - vec[RSHO][0]
    return None if abs(d) < margin else ("front" if d > 0 else "back")


def readability(vec, tags, nonstandard=False):
    """How well Spellbook could read a skeleton: ("clear" | "partial" | "unclear", reason).
    clear: 8+ body joints and a known facing, so pose check, facing check and the facing word filter all work.
    partial: readable but facing unknown or few joints. unclear: too few joints read, or a non-standard drawing."""
    if nonstandard:
        return "unclear", "drawn in a non-standard style"
    n = sum(1 for i in BODY if vec and vec[i] is not None)
    if n < 5:
        return "unclear", f"only {n} of 12 body joints could be read"
    if not any(t in (tags or []) for t in ("front view", "from behind", "from side")):
        return "partial", "facing unknown"
    if n < 8:
        return "partial", f"{n} of 12 body joints read"
    return "clear", ""


def from_openpose_json(person, width, height):
    """COCO-18 keypoints from OpenPose JSON (pose_keypoints_2d: x, y, confidence triples). Coordinates may be
    normalized (0..1) or pixels; low-confidence joints count as missing."""
    k = person.get("pose_keypoints_2d") or []
    kp = []
    for i in range(18):
        x, y, c = (k[i * 3: i * 3 + 3] + [0, 0, 0])[:3]
        if c < 0.3 or (x == 0 and y == 0):
            kp.append(None)
            continue
        if x <= 1.0 and y <= 1.0:
            x, y = x * width, y * height
        kp.append(np.array([x, y], dtype=np.float32))
    return kp


def analyze(path):
    try:
        kp, people, size = keypoints(path)
        return {"tags": tags_for(kp, people, size), "v": vector(kp)}
    except Exception as e:
        return {"tags": [], "v": None, "err": str(e)[:80]}


# packs drawn with their own colour scheme (a red neck->pelvis spine, other limb colours): joints read from hue are
# unreliable there, so no view tags (and no facing check) for them
NONSTANDARD_PACKS = ("1000 Boudoir Glam shot Poses",)
VIEW_TAGS = {"front view", "from side", "from behind", "looking back"}


def _job(args):
    pid, path = args
    return pid, analyze(path)


def main():
    if sys.argv[1] == "--one":
        print(json.dumps(analyze(sys.argv[2]), indent=1))
        return
    root = os.path.abspath(sys.argv[1])
    idx = json.load(open(os.path.join(root, "index.json")))
    packs = {x["id"]: x.get("pack") for x in idx}
    out = {}
    with ProcessPoolExecutor(max_workers=max(2, (os.cpu_count() or 4) - 2)) as ex:
        for n, (pid, res) in enumerate(ex.map(_job, [(x["id"], os.path.join(root, x["path"])) for x in idx], chunksize=32), 1):
            if packs.get(pid) in NONSTANDARD_PACKS:
                res["tags"] = [t for t in res["tags"] if t not in VIEW_TAGS]
            out[pid] = res
            if n % 1000 == 0:
                print(n, flush=True)
    json.dump(out, open(os.path.join(root, "features.json"), "w"))
    tagged = sum(1 for r in out.values() if r["tags"])
    vec = sum(1 for r in out.values() if r["v"])
    print(f"done: {len(out)} poses, {tagged} tagged, {vec} with joint vectors")


if __name__ == "__main__":
    main()
