# standalone/

The application lives here.

- `server.py` — the FastAPI local server (and web/app shell entry point)
- `web/` — the web UI: plain ES modules, no build step
- `launch.sh` / `launch.ps1` — start the app (native window) or web mode
- `pose-starter/` — the bundled 44-pose starter kit (app-generated content)
- `krita_ai_bridge/` — the Krita AI Prompt Bridge add-on (`build.sh` compiles
  the notifier in `notifier/`); install instructions in the repository README

The prompt-library code (`lib_pl/`) and app configuration (`presets.json`) are
one level up, next to this folder.

See the repository root README for the full quickstart, platform table and
license.
