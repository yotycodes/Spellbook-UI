"""Spellbook themes: one registry, every Spellbook color token derived from it, contrast-checked, written to
standalone/web/themes.css (CSS) and themes.json (the Settings gallery).

  python -m lib_pl.themes        # rebuild themes.css / themes.json after editing THEMES

Catalog themes (premium_theme_catalog.json, dark variants) give 9 colors; the rest are derived. Their borders are
divider-strength (~1.5:1), so control edges get their own color lifted to 3:1. Status colors (ok/warn/danger) stay
global on purpose: they never change meaning between themes.
"""
import json
import os

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "standalone", "web")

# id, name, mood, then either a catalog palette (9 colors) or explicit Spellbook tokens
THEMES = [
    {"id": "graphite", "name": "Graphite", "mood": "Neutral gray, brand teal accent. The default.", "tokens": {
        "bg": "#0d0e10", "surface": "#141518", "surface-2": "#1a1b1f", "surface-3": "#212328", "surface-float": "#1d1e22",
        "line": "#25272c", "line-2": "#31343a", "line-hover": "#3d4047", "line-control": "#6c717a",
        "text": "#e9eaec", "text-2": "#b4b7bd", "muted": "#8a8e96", "faint": "#8a8f98", "faint-ui": "#5f636b", "stage": "#08090a",
        "accent": "#00d5d8", "accent-hover": "#2be1e3", "accent-text": "#69e9ea", "accent-soft": "#0e3a3d", "accent-ring": "#1b8a8d",
        "accent-fill": "#0a7f84", "accent-fill-hover": "#087074", "accent-ink": "#ffffff"}},
    {"id": "oled", "name": "OLED Black", "mood": "True black, blue accent. Best on OLED screens.", "tokens": {
        "bg": "#000000", "surface": "#0a0a0b", "surface-2": "#111113", "surface-3": "#18181b", "surface-float": "#151517",
        "line": "#1d1d21", "line-2": "#2a2a2f", "line-hover": "#36363c", "line-control": "#67676f",
        "text": "#ececee", "text-2": "#b6b6bc", "muted": "#8d8d95", "faint": "#8e8e96", "faint-ui": "#55555c", "stage": "#000000",
        "accent": "#4d8dff", "accent-hover": "#6a9fff", "accent-text": "#76a7ff", "accent-soft": "#0f1c33", "accent-ring": "#2a4f8c",
        "accent-fill": "#2d6ae0", "accent-fill-hover": "#2a63d4", "accent-ink": "#ffffff"}},
    {"id": "midnight-graphite", "name": "Midnight Graphite", "mood": "Sleek, focused. Navy surfaces, ice-blue accent.", "catalog": {
        "background": "#0B1020", "surface": "#121B31", "surfaceElevated": "#1C2842", "text": "#F5F7FF", "textMuted": "#BAC5DA",
        "border": "#34435E", "accent": "#8CB4FF", "accentOn": "#08152B", "accentSoft": "#24365B"}},
    {"id": "warm-paper", "name": "Warm Paper", "mood": "Warm, editorial. Espresso surfaces, tan accent.", "catalog": {
        "background": "#1A1714", "surface": "#24201B", "surfaceElevated": "#302921", "text": "#F7EFE4", "textMuted": "#D0C0AE",
        "border": "#514538", "accent": "#D6B487", "accentOn": "#24170B", "accentSoft": "#423324"}},
    {"id": "sage-studio", "name": "Sage Studio", "mood": "Calm, grounded. Forest surfaces, sage accent.", "catalog": {
        "background": "#111A14", "surface": "#19251C", "surfaceElevated": "#233328", "text": "#F1F7F0", "textMuted": "#BED0C0",
        "border": "#354C3B", "accent": "#91D4A9", "accentOn": "#102319", "accentSoft": "#284633"}},
    {"id": "ocean-glass", "name": "Ocean Glass", "mood": "Clear, cool. Deep-ocean surfaces, aqua accent.", "catalog": {
        "background": "#0C1A20", "surface": "#13272F", "surfaceElevated": "#1E3740", "text": "#F0FAFC", "textMuted": "#B7D0D6",
        "border": "#35515B", "accent": "#76D8E6", "accentOn": "#092228", "accentSoft": "#204852"}},
    {"id": "lavender-cloud", "name": "Lavender Cloud", "mood": "Soft, creative. Plum surfaces, lilac accent.", "catalog": {
        "background": "#171222", "surface": "#211A31", "surfaceElevated": "#2E2543", "text": "#F8F3FF", "textMuted": "#D2C5E7",
        "border": "#453758", "accent": "#C4A5FF", "accentOn": "#28143D", "accentSoft": "#3D2B57"}},
    {"id": "cherry-noir", "name": "Cherry Noir", "mood": "Rich, expressive. Burgundy surfaces, rose accent.", "catalog": {
        "background": "#1E1017", "surface": "#2A1720", "surfaceElevated": "#38202C", "text": "#FFF1F5", "textMuted": "#E1BCC9",
        "border": "#573543", "accent": "#FF91B5", "accentOn": "#3A0B1F", "accentSoft": "#5B223A"}},
    {"id": "retro-arcade", "name": "Retro Arcade", "mood": "Playful, bold. Midnight purple, electric mint.", "catalog": {
        "background": "#100D1C", "surface": "#19142B", "surfaceElevated": "#271E41", "text": "#F9F5FF", "textMuted": "#C9BDED",
        "border": "#42335F", "accent": "#67F2D0", "accentOn": "#07251C", "accentSoft": "#30234E"}},
    {"id": "monochrome", "name": "Monochrome Contrast", "mood": "Black and white, strongest contrast.", "catalog": {
        "background": "#000000", "surface": "#0F0F0F", "surfaceElevated": "#1C1C1C", "text": "#FFFFFF", "textMuted": "#D6D6D6",
        "border": "#777777", "accent": "#FFFFFF", "accentOn": "#000000", "accentSoft": "#2A2A2A"}},
]
DEFAULT = "graphite"

# minimum contrast per pair (WCAG): body text 7:1 (Apple's recommendation for custom pairs), small text 4.5:1,
# control edges and the accent as an indicator 3:1
LIMITS = {"text": 7.0, "text-2": 4.5, "muted": 4.5, "faint": 4.5, "line-control": 3.0, "accent": 3.0,
          "accent-text on soft": 4.5, "text on soft": 4.5, "ink on fill": 4.5, "ink on fill-hover": 4.5}


def _rgb(h):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def _hex(rgb):
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def mix(a, b, t):
    """t of a, (1 - t) of b."""
    return _hex([x * t + y * (1 - t) for x, y in zip(_rgb(a), _rgb(b))])


def contrast(a, b):
    def lum(h):
        f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        r, g, b_ = [f(c / 255) for c in _rgb(h)]
        return 0.2126 * r + 0.7152 * g + 0.0722 * b_
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _lift(color, toward, against, need):
    """Move color toward `toward` until it reaches `need` contrast against every color in `against`."""
    for i in range(101):
        c = mix(toward, color, i / 100)
        if min(contrast(c, x) for x in against) >= need:
            return c
    return toward


def derive(c):
    """Spellbook tokens from a 9-color catalog palette."""
    bg, s, s3 = c["background"], c["surface"], c["surfaceElevated"]
    s2 = mix(s3, s, 0.5)
    surfaces = [bg, s, s2, s3]
    muted = _lift(mix(c["textMuted"], s, 0.78), c["textMuted"], surfaces, 4.8)
    fill_hover = mix("#ffffff", c["accent"], 0.12)
    if contrast(c["accentOn"], fill_hover) < 4.5:
        fill_hover = mix("#000000", c["accent"], 0.08)
    return {
        "bg": bg, "surface": s, "surface-2": s2, "surface-3": s3, "surface-float": s3,
        "line": mix(c["border"], s, 0.6), "line-2": c["border"], "line-hover": mix(c["text"], c["border"], 0.12),
        "line-control": _lift(c["border"], c["textMuted"], surfaces, 3.1),
        "text": c["text"], "text-2": c["textMuted"], "muted": muted, "faint": muted, "faint-ui": mix(c["textMuted"], s, 0.4),
        "stage": mix("#000000", bg, 0.4),
        "accent": c["accent"], "accent-hover": mix("#ffffff", c["accent"], 0.15), "accent-text": c["accent"],
        "accent-soft": c["accentSoft"], "accent-ring": mix(c["accent"], s, 0.5),
        "accent-fill": c["accent"], "accent-fill-hover": fill_hover, "accent-ink": c["accentOn"],
    }


def tokens(theme):
    return dict(theme["tokens"]) if "tokens" in theme else derive(theme["catalog"])


def check(t):
    """{pair: (contrast, limit)} for every pair below its limit."""
    surfaces = [t["bg"], t["surface"], t["surface-2"], t["surface-3"], t["surface-float"]]
    got = {k: min(contrast(t[k], x) for x in surfaces) for k in ("text", "text-2", "muted", "faint", "line-control", "accent")}
    got.update({"accent-text on soft": contrast(t["accent-text"], t["accent-soft"]), "text on soft": contrast(t["text"], t["accent-soft"]),
                "ink on fill": contrast(t["accent-ink"], t["accent-fill"]), "ink on fill-hover": contrast(t["accent-ink"], t["accent-fill-hover"])})
    return {k: (round(v, 2), LIMITS[k]) for k, v in got.items() if v < LIMITS[k]}


def css():
    out = ["/* Generated by lib_pl/themes.py: edit the registry there, then run `python -m lib_pl.themes`. */"]
    for th in THEMES:
        sel = ":root" if th["id"] == DEFAULT else f':root[data-theme="{th["id"]}"]'
        body = "\n".join(f"  --{k}: {v};" for k, v in tokens(th).items())
        out.append(f"{sel} {{\n{body}\n}}")
    return "\n".join(out) + "\n"


def gallery():
    """What the Settings gallery needs to draw each card."""
    keys = ("bg", "surface", "surface-3", "line-2", "text", "text-2", "accent", "accent-fill", "accent-ink", "accent-soft")
    return {"default": DEFAULT, "themes": [{"id": th["id"], "name": th["name"], "mood": th["mood"],
                                             "colors": {k: tokens(th)[k] for k in keys}} for th in THEMES]}


def build():
    bad = {th["id"]: check(tokens(th)) for th in THEMES}
    bad = {k: v for k, v in bad.items() if v}
    if bad:
        raise SystemExit(f"contrast below the limits: {bad}")
    with open(os.path.join(WEB, "themes.css"), "w") as f:
        f.write(css())
    with open(os.path.join(WEB, "themes.json"), "w") as f:
        json.dump(gallery(), f, indent=1)
    return len(THEMES)


if __name__ == "__main__":
    print(f"wrote {build()} themes")
