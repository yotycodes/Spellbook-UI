"""Pose tags: find them in a prompt and swap them for a Pose Kit preset (tags + matching OpenPose skeleton)."""
import json
import os
import re

from .tagclean import clean, key, rewrap, split_top, unwrap

_W_SUFFIX_RX = re.compile(r":\s*-?[\d.]+\s*$")

_BETA_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Tracked starter kit: app-generated poses shipped with the app.
# A custom .pose-kit, when present, adds/overrides on top of it.
SHIP_KIT = os.path.join(_BETA_ROOT, "standalone", "pose-starter")


def _user_kit_dir():
    """Also honor spellbook.json (same precedence as paths.py: env > config > .pose-kit)."""
    env = os.environ.get("SPELLBOOK_POSE_KIT")
    if env:
        return os.path.expanduser(env)
    try:
        with open(os.path.join(_BETA_ROOT, "spellbook.json")) as f:
            guess = json.load(f).get("pose_kit_dir")
    except (OSError, ValueError):
        guess = None
    return os.path.expanduser(guess) if guess else os.path.join(_BETA_ROOT, ".pose-kit")


POSE_KIT = _user_kit_dir()

_POSE_RX = re.compile(
    r"\b(standing|stand|sitting|seated|kneeling|kneel|lying|reclining|squatting|crouching|leaning|bent over|bending|"
    r"walking|running|sprinting|jumping|midair|flying|kicking|punching|reaching|pointing|stretching|arched back|"
    r"contrapposto|hip pop|s-curve|crossed legs|legs crossed|crossed ankles|legs apart|spread legs|wide stance|"
    r"one knee|knees? up|leg up|legs up|on back|on stomach|on side|all fours|seiza|"
    r"hands? (on|behind|in|up|together|on own)|arms? (up|behind|crossed|raised|out|forward|above|at sides)|"
    r"hand on|hands on|holding|looking (back|over|at viewer|away|up|down|to the side)|"
    r"from (below|above|behind|side)|dutch angle|dynamic (pose|angle)|pose|posing|stance|fighting|v sign|peace sign|"
    r"outstretched|clenched hands?|fist|salute|waving|head tilt|tilted head|turning|twisted torso|foreshortening|"
    r"over shoulder|cowboy shot|full body|upper body|portrait|close-up)\b", re.I)
_FX = re.compile(r"\b(speed lines|motion lines|motion blur|dust|debris|wind|impact|glowing|light rays|shockwave|"
                 r"cracked ground|ground cracking|flying rocks|swirling sand|sand wave|bed)\b", re.I)


def is_pose_tag(tag):
    return bool(_POSE_RX.search(key(tag)))


def detect(prompt):
    """(pose_tags, other_tags) — keeps original spelling/weights."""
    pose, rest = [], []
    for t in split_top(prompt or ""):
        (pose if not t.startswith("<") and is_pose_tag(t) else rest).append(t)
    return pose, rest


def swap(prompt, new_pose):
    """Replace the prompt's pose tags with new_pose (comma string). Everything else stays, in order."""
    _, rest = detect(prompt)
    out, _ = clean(", ".join(rest + split_top(new_pose or "")))
    return out


# ---- merge(): add a pose's tags and drop the prompt tags that would fight the skeleton.
# Tags fall into groups; inside a group the pose defines, the pose wins. Groups the pose leaves open are kept,
# so "looking at viewer" survives a pose that only says "lying". Anything outside every group (character,
# outfit, props like "holding sword", style, LoRAs) is never touched.
_G = lambda *pats: re.compile(r"^(?:" + "|".join(pats) + r")$")  # noqa: E731
POSE_GROUPS = {
    "posture": _G(r"standing( on one leg)?", r"stand", r"sitting( on .+)?", r"seated", r"kneeling( on .+)?", r"on knees?",
                  r"one knee", r"lying( on .+)?", r"on (back|stomach|side)", r"reclining", r"squatting", r"crouching",
                  r"(on )?all fours", r"bent over", r"bending( over)?", r"walking", r"running", r"sprinting",
                  r"jumping", r"midair", r"flying", r"seiza", r"wariza", r"indian style", r"leaning( forward| back)?",
                  r"wading", r"floating", r"swimming", r"bending forward", r"top-down bottom-up", r"on (own )?(knees|side)"),
    "view": _G(r"from (behind|side|front)", r"(front|back|side) view", r"facing (viewer|away)", r"profile"),
    "height": _G(r"from (above|below)", r"(high|low) angle", r"bird'?s?[- ]eye view", r"worm'?s?[- ]eye view",
                 r"eye[- ]level( shot| view)?", r"straight[- ]on", r"dutch angle", r"tilted (frame|angle)", r"dynamic angle",
                 r"fisheye( lens)?", r"foreshortening", r"perspective", r"pov"),
    "torso": _G(r"arched back", r"back arch(ed)?", r"arching( (her|own))? back", r"twisted torso", r"torso twist", r"twisting",
                r"hunched( over)?", r"slouching", r"(chest|breasts?) (out|forward)", r"hips? (out|thrust( forward)?)"),
    "framing": _G(r"full body", r"upper body", r"lower body", r"cowboy shot", r"portrait", r"close[- ]?up( shot)?", r"extreme close[- ]?up",
                  r"medium (close[- ]?up|shot)", r"zoomed (in|out)", r"thigh[- ]?up", r"knee[- ]?up", r"headshot",
                  r"bust", r"head and shoulders", r"feet out of frame", r"wide shot"),
    "arms": _G(r"arms? up", r"arms? raised", r"hands? up", r"arms? behind (back|head)", r"hands? behind (back|head)",
               r"crossed arms", r"arms crossed", r"hands? on (own )?hips?", r"outstretched arms?", r"arms? out",
               r"spread arms", r"arms? at sides?", r"hands? together", r"hands? on (own )?(face|head|cheek|chest)",
               r"hands? in (own )?hair", r"reaching( out)?", r"pointing", r"v sign", r"peace sign", r"salute", r"waving",
               r"arms? under (own )?breasts?", r"arms? (folded|crossed)", r"arm support", r"hands? on (own )?(thighs?|knees?|lap|ass|butt)",
               r"hands? between (own )?legs", r"arms? (behind|over) (own )?head", r"hands? on (own )?(chest|breasts?)",
               r"(arms?|hands?|elbows?) resting( on .+)?", r"arms? (at|by) (her |his |own )?sides?", r"hands? in (own |her )?lap",
               r"arms? (down|lowered|folded|wrapped around .+)", r"hands? on (the )?(ground|floor|bench|table|knees)", r"arm support"),
    "legs": _G(r"crossed legs", r"legs crossed", r"legs apart", r"spread legs", r"wide stance", r"legs? up", r"knees? up",
               r"knees together", r"crossed ankles", r"legs together", r"knees to chest", r"legs? (spread|open)",
               r"knees? apart", r"leg lift", r"splits?", r"standing split", r"one leg up"),
    "gaze": _G(r"looking (back|at viewer|away|up|down|to the side|over (own )?shoulder|ahead)"),
    "action": _G(r"dynamic pose", r"fighting stance", r"kicking", r"high kick", r"punching", r"action pose"),
}
# only make sense on your feet: dropped whenever the pose sets a posture that isn't standing/walking
_STANDING_ONLY = _G(r"contrapposto", r"wide stance", r"hip pop", r"standing on one leg", r"s-curve")
_UPRIGHT = _G(r"standing", r"stand", r"walking", r"running", r"sprinting", r"jumping", r"midair", r"flying")


def _group(k):
    return next((g for g, rx in POSE_GROUPS.items() if rx.match(k)), None)


_SAME = {"back view": "from behind", "rear view": "from behind", "from back": "from behind", "facing away": "from behind",
         "front view": "from front", "facing viewer": "from front", "side view": "from side", "profile": "from side",
         "hand on hip": "hand on own hip", "hands on hips": "hands on own hips", "arms raised": "arms up"}


def _compatible(a, b):
    """'lying' and 'lying on back' agree (one is a word-prefix of the other); so do synonyms (back view = from behind)."""
    a, b = _SAME.get(a, a), _SAME.get(b, b)
    return a == b or a.startswith(b + " ") or b.startswith(a + " ")


def merge(prompt, pose_tags):
    """Returns (prompt, removed, added). Pose tags go at the end; conflicting prompt tags are removed;
    duplicates are cleaned. LoRAs, [a:b] edits and {a|b} groups are left alone.
    When the pose words it more precisely ("lying" -> "lying on back") the pose's words take the tag's place and keep
    its emphasis: ((lying:1.4)) -> ((lying on back:1.4))."""
    tags = split_top(prompt or "")
    pose = [t for t in split_top(pose_tags or "") if t]
    pkeys = [key(t) for t in pose]
    defined = {g for g in map(_group, pkeys) if g}
    if pkeys:   # the skeleton itself sets the camera angle and the torso's shape, whether its tags say so or not
        defined |= {"height", "torso"}
    posture = [k for k in pkeys if _group(k) == "posture"]
    not_upright = bool(posture) and not any(_UPRIGHT.match(k) for k in posture)
    kept, removed, covered = [], [], set()
    for t in tags:
        if t[:1] in "<[{":
            kept.append(t)
            continue
        k = key(t)
        g = _group(k)
        if g in defined:
            same = [pk for pk in pkeys if _group(pk) == g]
            match = k if k in same else next((pk for pk in same if _compatible(k, pk)), None)
            if match is None or (match != k and not all(_compatible(k, pk) for pk in same)):
                removed.append(t)
                continue
            covered.add(match)
            if len(k) < len(match) and _SAME.get(k, k) != _SAME.get(match, match):   # pose is more specific: its wording,
                removed.append(t)                                                    # in place and with your emphasis
                kept.append(rewrap(t, pose[pkeys.index(match)]))
                continue
        elif not_upright and _STANDING_ONLY.match(k):
            removed.append(t)
            continue
        kept.append(t)
    seen = {key(t) for t in kept}
    added = [t for t, k in zip(pose, pkeys) if k not in covered and k not in seen]
    out, _ = clean(", ".join(kept + added))
    removed = [t for i, t in enumerate(removed) if key(t) not in {key(x) for x in removed[:i]}]
    return out, removed, added


# ---- resolve(): conflicts inside one prompt (auto-clean). Tags belong to "families"; two tags from different
# families of the same kind can't both be true (standing vs sitting, from front vs from behind). First written wins.
_FAMILIES = {
    "posture": {"stand": _G(r"standing( on one leg)?", r"stand"),
                "sit": _G(r"sitting( on .+)?", r"seated", r"seiza", r"wariza", r"indian style"),
                "kneel": _G(r"kneeling( on .+)?", r"on knees?", r"one knee"),
                "lie": _G(r"lying", r"reclining"),
                "lie back": _G(r"lying on back", r"on back"),
                "lie stomach": _G(r"lying on stomach", r"on stomach"),
                "lie side": _G(r"lying on side", r"on side"),
                "squat": _G(r"squatting", r"crouching"),
                "fours": _G(r"(on )?all fours")},
    "view": {"behind": _G(r"from behind", r"back view", r"facing away"),
             "front": _G(r"from front", r"front view", r"facing viewer"),
             "side": _G(r"from side", r"side view", r"profile")},
    "height": {"above": _G(r"from above", r"high angle", r"bird'?s?[- ]eye view"),
               "below": _G(r"from below", r"low angle", r"worm'?s?[- ]eye view")},
}


def _family(k):
    for kind, fams in _FAMILIES.items():
        for name, rx in fams.items():
            if rx.match(k):
                return kind, name
    return None, None


def _fam_ok(a, b):
    """Same family, or generic 'lie' with any lying direction."""
    return a == b or (a.startswith("lie") and b.startswith("lie") and "lie" in (a, b))


def resolve(prompt):
    """(prompt, removed): drops later tags that contradict an earlier one (posture, view direction, camera height).
    Each BREAK/AND/line segment is checked on its own; LoRAs, [a:b] and {a|b} are untouched."""
    from .tagclean import _SEGMENT
    if not prompt or not prompt.strip():
        return prompt, []
    removed, out = [], []
    for part in _SEGMENT.split(prompt):
        if _SEGMENT.fullmatch(part or "") or not part.strip():
            out.append(part)
            continue
        chosen, kept = {}, []
        for t in split_top(part):
            kind, fam = (None, None) if t[:1] in "<[{" else _family(key(t))
            if kind:
                if any(not _fam_ok(f, fam) for f in chosen.get(kind, [])):
                    removed.append(t)
                    continue
                chosen.setdefault(kind, []).append(fam)
            kept.append(t)
        lead = part[:len(part) - len(part.lstrip())]
        trail = part[len(part.rstrip()):]
        out.append(lead + ", ".join(kept) + trail if len(kept) != len(split_top(part)) else part)
    return "".join(out), removed


def _label(name):
    group, _, rest = name.partition("_")
    nice = {"pinup": "Pin-up", "fashion": "Fashion", "boudoir": "Boudoir"}.get(group)
    words = (rest if nice else name).replace("_", " ")
    return f"{nice} · {words}" if nice else f"Action · {words}"


def _kit(kit):
    """Raw {key: {"tags","skeleton","note","canvas"}} for one kit dir; missing kit → {}."""
    try:
        with open(os.path.join(kit, "poses.json"), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    out = {}
    for name, v in data.items():
        tags = ", ".join(t for t in split_top(v.get("tags", "")) if not _FX.search(t))
        skel = None
        for sub, suffix in (("portrait", "_adult"), ("boudoir", "_adult"), ("chibi", "_chibi")):
            p = os.path.join(kit, sub, f"{name}{suffix}.png")
            if os.path.exists(p):
                skel = p
                break
        out[name] = {"key": name, "tags": tags, "skeleton": skel, "note": v.get("note", ""),
                     "canvas": v.get("canvas", "832x1216")}
    return out


def presets(kit=POSE_KIT):
    """{label: {"key", "tags" (pose tags only, no FX), "skeleton" path or None}} for the merged kit set:
    the shipped starter kit always, plus the user/.pose-kit as an overlay (same key wins)."""
    merged = {}
    has_ship = os.path.isdir(SHIP_KIT) and os.path.exists(os.path.join(SHIP_KIT, "poses.json"))
    scanned = _kit(kit) if os.path.isdir(kit) and kit != SHIP_KIT else {}
    if not has_ship:  # a fresh mirror without standalone/pose-starter: the local kit is the only source
        scanned = _kit(kit)
    merged.update(_kit(SHIP_KIT))
    merged.update(scanned)
    order = {"Pin-up": 0, "Fashion": 1, "Boudoir": 2, "Action": 3}
    out = {}
    for name, v in merged.items():
        label = _label(name)
        out[label] = {"key": v["key"], "tags": v["tags"], "skeleton": v["skeleton"], "note": v["note"],
                      "canvas": v["canvas"]}
    return dict(sorted(out.items(), key=lambda kv: (order.get(kv[0].split(" · ")[0], 9), kv[0])))


# ---- facing_filter(): words that only make sense from one side pull the body around to that side, fighting a
# back (or front) skeleton. Matched anywhere inside a tag, so "view from behind touching ..." counts too.
_W = lambda *pats: re.compile(r"\b(?:" + "|".join(pats) + r")\b")  # noqa: E731
_FRONT_ONLY = _W(r"front view", r"from (the )?front", r"facing (the )?viewer", r"straight[- ]on", r"cleavage",
                 r"navel", r"belly button", r"midriff", r"(?<!on )stomach", r"abs", r"toned (stomach|abs|belly)", r"(?<!on )belly",
                 r"collarbones?", r"chest", r"breasts?", r"boobs?", r"tits?", r"nipples?", r"underboob", r"sideboob",
                 r"breast focus", r"pov")
_FACE_ONLY = _W(r"looking at viewer", r"eye contact", r"face focus", r"(adult|cute|detailed|beautiful|pretty) face",
                r"open mouth", r"smil(e|ing)", r"grin(ning)?", r"blush(ing)?", r"tongue( out)?", r"ahegao", r"wink(ing)?",
                r"parted lips", r"lips", r"teeth", r"facial expression", r"expression")
# a body seen from behind only shows these when bent over, on all fours, kneeling, lying or with legs open/up
_CROTCH = _W(r"pussy( focus| juice| peek)?", r"wet spot", r"cameltoe", r"crotch( focus)?", r"groin", r"pubic hair", r"clitoris",
             r"spread pussy", r"grool", r"vulva", r"labia", r"penis", r"erection", r"bulge")
_CROTCH_FROM_BEHIND = _G(r"bent over", r"bending( over| forward)?", r"(on )?all fours", r"kneeling( on .+)?", r"on knees?", r"lying( on .+)?",
                         r"on (back|stomach|side)", r"top-down bottom-up", r"legs? (up|spread|open)", r"spread legs", r"leg up",
                         r"squatting", r"crouching", r"legs apart", r"knees? up")
_BACK_ONLY = _W(r"from behind", r"from (the )?back", r"back view", r"rear view", r"facing away", r"looking back",
                r"looking over (own |her |his )?shoulder", r"over (the )?shoulder", r"back focus", r"bare back",
                r"back tattoo", r"(ass|butt) focus", r"backless", r"turned away")


def facing_filter(prompt, facing, face_visible=True, pose_tags=None):
    """Drop prompt tags that point the body the other way. facing: "back" or "front" (anything else: no change).
    A back view with no face drawn (not looking back) also loses face-only words. LoRAs, wildcards and prompt
    edits are never touched. Returns (prompt, removed)."""
    if facing not in ("back", "front"):
        return prompt, []
    rx = [_FRONT_ONLY] + ([] if face_visible else [_FACE_ONLY]) if facing == "back" else [_BACK_ONLY]
    if facing == "back" and pose_tags is not None:   # standing / sitting back view: nothing between the legs is in view
        tags = [key(t) for t in (split_top(pose_tags) if isinstance(pose_tags, str) else pose_tags)]
        if not any(_CROTCH_FROM_BEHIND.match(t) for t in tags):
            rx.append(_CROTCH)
    removed = []

    def keep(t):
        """The tag, the group with its matching words taken out, or None. ((1girl, dva, cleavage)) keeps the
        character and loses only 'cleavage' instead of the whole group."""
        if t[:1] in "<[{":
            return t
        inner = unwrap(t)
        if inner != t.strip() and len(split_top(inner)) > 1:
            kids = [k for k in (keep(x) for x in split_top(inner)) if k]
            if not kids:
                return None
            if len(kids) == len(split_top(inner)):
                return t
            lead = t[:len(t) - len(t.lstrip("("))]
            weight = _W_SUFFIX_RX.search(t.strip()[len(lead):-len(lead)] if lead else "")
            return f"{lead}{', '.join(kids)}{weight.group(0) if weight else ''}{')' * len(lead)}"
        if any(r.search(key(t)) for r in rx):
            removed.append(t)
            return None
        return t
    kept = [k for k in (keep(t) for t in split_top(prompt or "")) if k]
    return (", ".join(kept), removed) if removed else (prompt, [])


def pose_facing(pose_tags):
    """(facing, face_visible) from a pose's tag list or comma string."""
    tags = {key(t) for t in (split_top(pose_tags) if isinstance(pose_tags, str) else pose_tags or [])}
    if tags & {"from behind", "back view", "back"}:
        return "back", bool(tags & {"looking back", "looking over shoulder", "looking over own shoulder"})
    if "front view" in tags:
        return "front", True
    return None, True


def pose_wins(prompt, pose_words):
    """Remove the prompt tags that fight the pose (same rules as merge), without adding anything. For the
    automatic clean-up and the final prompt: a picked pose always wins, weighted words included. Returns (prompt, removed)."""
    if not (pose_words or "").strip():
        return prompt, []
    # pose words inside a multi-tag group, e.g. ((mikasa, sitting, crossed legs:1.3)), are checked one by one
    tags, grouped = split_top(prompt or ""), []
    for i, t in enumerate(tags):
        inner = unwrap(t)
        if t[:1] == "(" and inner != t.strip() and len(split_top(inner)) > 1:
            kept, gone = pose_wins(inner, pose_words)
            if gone:
                grouped += gone
                lead = t[:len(t) - len(t.lstrip("("))]
                w = _W_SUFFIX_RX.search(t.strip()[len(lead):-len(lead)])
                tags[i] = f"{lead}{kept}{w.group(0) if w else ''}{')' * len(lead)}" if kept.strip() else ""
    if grouped:
        prompt = ", ".join(t for t in tags if t)
    _, removed, _ = merge(prompt, pose_words)
    removed = grouped + removed
    if not removed:
        return prompt, []
    gone = {key(t) for t in removed}
    swap = {key(t): rewrap(t, w) for t in removed for w in _more_specific(key(t), pose_words)}
    out = [swap.get(key(t), t) if key(t) in swap else t for t in split_top(prompt) if t[:1] in "<[{" or key(t) not in gone or key(t) in swap]
    return ", ".join(out), [t for t in removed if key(t) not in swap]


def _more_specific(k, pose_words):
    """Pose words that say the same thing as tag key k, only more precisely (k = lying, pose = lying on back)."""
    return [w for w in split_top(pose_words or "") if key(w) != k and _compatible(k, key(w)) and len(key(w)) > len(k)
            and _SAME.get(k, k) != _SAME.get(key(w), key(w))][:1]
