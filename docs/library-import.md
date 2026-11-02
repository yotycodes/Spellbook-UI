# Library import & your prompt library

Spellbook UI's Library is *yours to fill*. This page covers every way to bring
prompts in, and how to move a library back out.

## The sidecar format

Your library is one folder with one file:

```
~/Documents/Spellbook UI/Library/all-prompts.json
```

Each record is a generation recipe:

```json
{
  "id": 9173928,                  // unique; records from civitai.com use the image id
  "base": "Illustrious",          // checkpoint family the record was generated with
  "nsfw": "None",                 // "None" | "Soft" | "Mature" | "X"
  "prompt": "a knight in ruins…",
  "neg": "blurry, watermark",
  "sampler": "DPM++ 2M Karras",
  "steps": 30, "cfg": 5, "size": "832x1216", "clip": 2,
  "res": [],                      // LoRA/embedding resources used, [{"n": name, "v": version, "t": "LORA", "w": 0.8}]
  "react": 0,                     // popularity (how it sorts)
  "source": "civitai"             // "civitai" | "png" | "csv" | "spellbook"
}
```

The file may be missing records' optional fields; Spellbook fills their
defaults (steps 30, cfg 7, size 832×1216).

## Import doors

### 1. Images with saved generation info (the main door)

Forge, A1111 and ComfyUI embed prompt + settings into exported PNGs. Point
**Library → Import images folder…** at any folder of them:

- every `.png` with generation info becomes a record (renderer's best effort)
- thumbnails render from the source images; the record keeps `img` pointing
  at the file, so don't delete/rename it after import
- PNGs without generation info are skipped (noted in the result toast)

### 2. Starter shelf (one click, 50 prompts)

The shipped **starter shelf** — 50 SFW prompts that run on a plain Illustrious
install with no LoRAs — is available inside the empty Library view:
**Add the starter shelf**. It merges (never overwrites).

### 3. Sidecar files (JSON / CSV)

**Import file (JSON / CSV)** accepts:

- the JSON format above (list of records) — yours or another user's
- a Civitai-style prompt CSV with columns
  `id,url,base,rating,reactions,prompt,negative,sampler,steps,cfg,size,clip_skip,resources`
  (`resources` lines like `LORA: Name (v1.0) @0.65 | …`)

Imports merge: matching ids or prompt texts are skipped, so re-importing is safe.

### 4. Set an existing library folder

If you already maintain a library folder elsewhere,
**Settings → Prompt library** repoints the app at it (same sidecar file).

## Export

**Settings → Library → Export** (or the Export action in the Library) writes
`spellbook-library.json` — the same sidecar format, ready to share or back up.

## Notes on Civitai

Record *cards* from Civitai download their thumbnails from `civitai.com`
when first viewed. Generation-meta (prompt text) is **not** fetched from
Civitai: their public API stopped exposing generation meta (verified Nov
2026), so an online import door would only import picture cards without
prompts — deliberately not shipped in v1.
