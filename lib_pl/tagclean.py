"""Prompt tag cleaner (same rules as the Krita AI Diffusion patch):
- removes duplicate tags (case, underscores, \\( escapes and (tag:1.2) weights ignored when comparing);
  if one copy carries a weight, the weighted copy is kept at the first position
- fixes common typos (masterpeice -> masterpiece, ...)
- positive prompts only: keeps one framing tag (full body / upper body / portrait / ...), the first one written
Never touches <lora:...>, BREAK / AND segments, [a:b:0.5] prompt editing or {a|b} wildcard groups —
each BREAK/AND/line segment is cleaned on its own."""
import re

FRAMING = {"full body", "upper body", "lower body", "portrait", "cowboy shot", "close-up", "headshot",
           "head and shoulders", "bust", "feet out of frame"}
TYPOS = {"masterpeice": "masterpiece", "masterpice": "masterpiece", "best qualty": "best quality",
         "high qualit": "high quality", "absurd res": "absurdres", "beautifull": "beautiful"}
_WEIGHT = re.compile(r"^\((.*):\s*[-\d.]+\)$")
_SEGMENT = re.compile(r"(\s*\bBREAK\b\s*|\s*\bAND\b\s*|\n)")


_PAIRS = {")": "(", "]": "[", "}": "{", ">": "<"}


def unmatched(text):
    """Positions of brackets with no partner (escaped \\( \\) don't count). A stray "(" pasted in from normal text
    would otherwise swallow every tag after it into one group."""
    stack, bad = [], set()
    for i, ch in enumerate(text):
        if i and text[i - 1] == "\\":
            continue
        if ch in "([{<":
            stack.append((ch, i))
        elif ch in _PAIRS:
            if stack and stack[-1][0] == _PAIRS[ch]:
                stack.pop()
            elif ch != ">":   # a lone ">" is usually just text (">_<", "->")
                bad.add(i)
    bad.update(i for ch, i in stack if ch != "<" or "lora:" not in text[i:i + 6])
    return bad


def split_top(text):
    """Split on commas outside (), [], {} and <>. Unmatched brackets are treated as plain text."""
    out, depth, cur = [], 0, []
    skip = unmatched(text)
    for i, ch in enumerate(text):
        if i not in skip and not (i and text[i - 1] == "\\"):
            if ch in "([{<":
                depth += 1
            elif ch in ")]}>" and depth:
                depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return [t.strip() for t in out if t.strip()]


def fix_brackets(prompt):
    """Drop unmatched ( ) [ ] { } so they can't weight or swallow the rest of the prompt. Returns (prompt, notes)."""
    bad = sorted(i for i in unmatched(prompt) if prompt[i] in "()[]{}")
    if not bad:
        return prompt, []
    chars = [prompt[i] for i in bad]
    out = "".join(ch for i, ch in enumerate(prompt) if i not in set(bad))
    return out, [f"removed unclosed {' '.join(dict.fromkeys(chars))}"]


_W_SUFFIX = re.compile(r":\s*-?[\d.]+\s*$")


def wraps(t):
    """True when t is one bracket group from its first to its last character: "((a:1.2))", not "(a), (b)"."""
    if len(t) < 2 or t[0] != "(" or t[-1] != ")":
        return False
    depth = 0
    for i, ch in enumerate(t):
        if i and t[i - 1] == "\\":
            continue
        depth += ch == "("
        depth -= ch == ")"
        if depth == 0 and i < len(t) - 1:
            return False
    return depth == 0


def unwrap(tag):
    """((crossed legs:1.4)) -> crossed legs. Strips any number of emphasis brackets and a :weight inside them."""
    t = tag.strip()
    while wraps(t):
        t = _W_SUFFIX.sub("", t[1:-1]).strip()
    return t


def rewrap(tag, word):
    """Put `word` inside the same emphasis as `tag`: rewrap("((lying:1.4))", "lying on back") -> "((lying on back:1.4))"."""
    t, n, weight = tag.strip(), 0, ""
    while wraps(t):
        inner = t[1:-1]
        m = _W_SUFFIX.search(inner)
        if m and not weight:
            weight = ":" + m.group(0).split(":", 1)[1].strip()
        t, n = _W_SUFFIX.sub("", inner).strip(), n + 1
    return f"{'(' * n}{word}{weight}{')' * n}" if n else word


def key(tag):
    t = unwrap(tag)
    t = t.replace("\\(", "(").replace("\\)", ")").replace("_", " ").lower()
    return " ".join(t.split())


def _weighted(tag):
    return bool(_WEIGHT.match(tag.strip()))


def _clean_segment(text, positive, state, notes):
    out, index = [], {}
    for tag in split_top(text):
        if tag[0] in "<[{":  # lora, prompt editing, wildcard group: keep as-is
            out.append(tag)
            continue
        k = key(tag)
        if state["typos"] and k in TYPOS:
            notes.append(f"typo {tag}->{TYPOS[k]}")
            tag, k = TYPOS[k], TYPOS[k]
        if positive and state["framing"] and k in FRAMING:
            if state["seen_framing"] and k != state["seen_framing"]:
                notes.append(f"dropped {tag} (kept {state['seen_framing']})")
                continue
            state["seen_framing"] = k
        if k in index:
            if _weighted(tag) and not _weighted(out[index[k]]):
                out[index[k]] = tag
            notes.append(f"dup {tag}")
            continue
        index[k] = len(out)
        out.append(tag)
    return ", ".join(out)


def clean(prompt, positive=True, framing=True, typos=True):
    """Returns (cleaned_prompt, notes). Segments split by BREAK/AND/newlines are deduped separately
    (repeats across AND regions are usually intentional); one framing tag is kept across the whole prompt."""
    if not prompt or not prompt.strip():
        return prompt, []
    prompt, notes = fix_brackets(prompt)
    state = {"framing": framing, "seen_framing": None, "typos": typos}
    parts = _SEGMENT.split(prompt)
    out = []
    for part in parts:
        if _SEGMENT.fullmatch(part or ""):
            out.append(part)
        else:
            out.append(_clean_segment(part, positive, state, notes) if part.strip() else part)
    return "".join(out), notes
