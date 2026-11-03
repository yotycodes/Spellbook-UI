# Changelog

All notable changes to Spellbook UI are documented here.

## Unreleased

### Added

- **Styles manager.** Generate → Style gains a + button opening Your Styles:
  list, create, edit, duplicate and delete styles in-app (JSON files in your
  styles folder, Krita-read-compatible format; the exact sampler is pinned via
  vendor keys). Krita-origin styles show read-only and get an "Adopt" copy
  action; brand-new styles hand straight to the Generate panel. Backed by
  `GET/POST/DELETE /api/styles` with server-side validation and clamps.

### Changed

- **Your styles, owned by Spellbook.** Styles now read from Spellbook's own
  editable folder, `~/Documents/Spellbook UI/Styles/` (env
  `SPELLBOOK_STYLES` › `spellbook.json` `styles_dir` › default), instead of
  reaching into Krita's hidden app data. Krita's styles folder remains a
  read-only fallback: its styles merge in under the same names when you have
  them, and Spellbook-folder styles shadow same-named Krita ones. Every style
  carries an `origin` tag (`spellbook` = editable, `krita` = read-only).
  UI copy drops the "Krita styles" phasing — they're just *your styles* now.

### Added

- **Library reset.** Settings → Prompt library gains a Reset button: empties
  the imported prompt library and clears favorites + collections, moving
  everything into a timestamped backup under app data (`library-backups/`)
  first. Thumbnail caches are cleared too (their ids can collide after a
  re-import). Requires a confirmation dialog; no app restart needed.

## 1.0.0 — 2026-11-01 (first public release)

### Added

- **Library import v1.** Build your prompt library from your own generations:
  drag in Forge/A1111/ComfyUI PNGs (the app reads their embedded generation
  info), a sidecar JSON/CSV, or the bundled 50-recipe starter shelf — all
  original, SFW, runnable on a plain Illustrious install. A `Runnable` filter
  surfaces only prompts your installed models can actually run.
- **Pose starter kit.** 44 app-generated poses (29 core + 15 authored
  OpenPose-format skeletons), shipped in-repo and browsable in the rail with
  skeleton previews and an SFW default. Point `spellbook.json` (`pose_kit_dir`,
  or the `SPELLBOOK_POSE_KIT` env var) at your own kit folder to extend or
  override individual poses — your kit wins on key conflicts.
- **Portable path resolution.** Every movable location — app data, Forge
  folder, pose kit, Krita styles, library — resolves env-var ›
  `spellbook.json` › platform default, and `spellbook.json` is written with
  nulls on first run. Fresh clones never carry personal state.
- **License layer.** AGPL-3.0 `LICENSE` for the app; `PACKS-LICENSE.md` for
  content terms (engine and in-repo generated content = AGPL; downloadable
  packs = per-pack terms; scraped-derived content ships free, never sold);
  vendored asset notices (Inter OFL 1.1, Phosphor MIT).
- **CI.** GitHub Actions: pytest (Ubuntu, Python 3.11)
  plus a `node --check` pass over every web UI module.
- **The prompt box, documented.** New README section with a screenshot:
  tag autocomplete from your own library's vocabulary, `⌘↑`/`⌘↓` weight
  dials, tag cleaning, and LoRA chip wiring.
- **Brand accent.** The app-wide accent is now the identity board's Mystic
  Teal `#00D5D8` (light theme carries the dark variant `#0A7F84`); contrast
  limits are enforced by the theme registry's own checks.
- **posekit vendored.** The pose-panel skeleton builder ships in-repo
  (`lib_pl/posekit.py`, self-authored) so a fresh clone — and CI — runs
  without external paths.
- **Krita handoff docs.** Install steps for the bundled AI Prompt Bridge
  add-on, and offline-first behavior verified end to end: every Krita surface
  degrades to a friendly, visible error without Krita.
- **Ship docs.** `README` (quickstart, platforms, where data lives, Krita
  steps), `docs/pose-packs.md`, `docs/library-import.md`, and the
  agent-collaboration conventions (`AGENTS.md`, `docs/agents/`).

### Notes

- The app drives the user's own Stable Diffusion **Forge** install through its
  API; Forge is a separate install and not a Python dependency.
- A past "Civitai URL" import door was replaced by the local PNG/sidecar
  import above: Civitai's public API stopped returning generation metadata,
  which made URL import unreliable for building libraries.
- 270-test pytest suite green; fresh-machine behavior (clone → launch → first
  image path and pose rail) verified on a scratch clone.
