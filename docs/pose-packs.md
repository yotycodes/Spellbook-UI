# Poses: the starter kit & adding your own

Spellbook UI ships with an **44-pose starter kit** — the 29 app-built
action/sheet poses plus 15 authored additions, each with a matching OpenPose
skeleton the pose rail can send to Forge's openpose ControlNet. They are
app-generated content, safe to redistribute, and need no download.

## Where they live

```
standalone/pose-starter/
├── poses.json        # the 44 pose records: tags, note, canvas
├── poses-29.json     # the 29 core kit poses (subset, kept for tooling/reference)
├── poses-15.json     # the 15 authored additions (tool-generated subset)
├── portrait/         # OpenPose-format skeletons, 512x768, <name>_adult.png
├── chibi/            # <name>_chibi.png
└── tools/make_skeletons.py   # regenerates the 15 authored skeletons
```

Your own kit lives elsewhere and is **overlaid on top** — nothing is copied
or moved.

## Which folder Spellbook uses

Pose lookup merges two directories, user-wins:

1. the shipped starter kit (`standalone/pose-starter/`) — always present
2. **your pose kit**, resolved in this order:
   - the `SPELLBOOK_POSE_KIT` environment variable
   - `pose_kit_dir` in `spellbook.json` (next to the repo root)
   - `.pose-kit/` in the repo root (developer convention)

A pose key present in both dirs takes your version — same tags, skeleton and
canvas — so you can extend or replace individual poses without touching the
shipped kit.

## Making your own kit

A kit folder needs:

```
my-kit/
├── poses.json        # {"pose_key": {"tags": "...", "note": "...", "canvas": "832x1216"}, ...}
└── portrait/         # skeleton per pose: pose_key_adult.png (chibi/: pose_key_chibi.png)
```

- **Skeletons** are OpenPose-format images (colored limbs on a black canvas,
  512×768 works well). The app reads joints from them for scoring and
  similarity; Forge's openpose ControlNet takes them directly.
- **tags** are the pose words merged into your prompt when a pose is applied —
  keep them pose-only ("kneeling, arched back, hands on thighs"), not
  scene/lighting words.
- **canvas** is the generation size the pose was drawn for.

Point `spellbook.json` at the folder:

```json
{ "pose_kit_dir": "/path/to/my-kit" }
```

and restart. Your poses appear in the pose rail; name-collisions with the
starter kit resolve to yours.

## Custom & Additional Pose Packs

The folder overlay described above is the primary way to load custom pose collections. Additional pose packs can simply be added to your configured `pose_kit_dir` to be recognized by the app.
