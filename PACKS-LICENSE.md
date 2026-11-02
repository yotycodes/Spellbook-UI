# PACKS-LICENSE — content licensing (stub; final text lands with the first pack drop)

Spellbook UI the app is AGPL-3.0 (see `LICENSE`). That license covers the
**engine**: source code (`lib_pl/`, `standalone/`, `tests/`, `install.py`,
`scripts/`) and the app-generated starter content tracked in this repo
(`standalone/pose-starter/`, `starter-shelf.json`), which ship under the same
AGPL so forked builds inherit improvements.

**The AGPL does NOT cover downloadable content packs.** Pack assets are licensed
per-pack at download time:

| Content | Source | License |
|---|---|---|
| Paid pose kits / style presets / LoRA recipes | App-generated, purpose-built for the pack | All-rights-reserved license grant: per-user download, **no redistribution, no resale, no republishing in other model corpora or datasets** |
| Free community pose kit | Scraped/derived from public sources | Free (free-as-in-the-thing), **never sold**; attribution license text ships with the kit |
| Starter shelf + tracked starter kit | In-repo, app-generated | AGPL-3.0, same as the engine |

### Content Licensing Guidelines:

- The engine never gets feature-paywalled; downloadable packs contain optional assets.
- Downloadable packs may not be re-hosted or resold by recipients without permission.
- Anything derived from community or open sources ships free with attribution.

Each downloadable pack carries its own license text upon download.
