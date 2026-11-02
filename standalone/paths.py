"""Central path resolution for Spellbook.

Precedence for every path: environment variable > ``spellbook.json`` (in the app root) >
platform default. The desktop launcher and a future installer only ever set environment
variables (or write this file) — release packaging never edits source paths.

The app-root default keeps existing checkout layouts working: if a checkout already has
``.beta-data`` (the legacy in-repo data dir), it stays the data dir; fresh machines get a
platform-appropriate user data location instead.
"""
import json
import os
import sys

_CONFIG = {}


def app_root():
    """The app's root directory (contains standalone/, lib_pl/, presets.json)."""
    return os.path.abspath(os.environ.get("SPELLBOOK_ROOT")
                           or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def config_path():
    return os.path.join(app_root(), "spellbook.json")


def _config():
    if not _CONFIG:
        try:
            with open(config_path()) as f:
                _CONFIG.update(json.load(f))
        except (OSError, ValueError):
            _CONFIG.update({})
    return _CONFIG


def reset_cache():
    """Reload spellbook.json on the next lookup (test hook)."""
    _CONFIG.clear()


def _pick(env_key, config_key, default):
    value = os.environ.get(env_key)
    if value:
        return os.path.abspath(os.path.expanduser(value))
    value = _config().get(config_key)
    if value:
        return os.path.abspath(os.path.expanduser(value))
    return os.path.normpath(os.path.expanduser(default)) if default else default


def app_data_dir():
    """App data root: settings, favorites, queue, thumbs, generations, logs."""
    configured = _config().get("app_data_dir")
    if os.environ.get("SPELLBOOK_APP_DIR"):
        return os.path.abspath(os.path.expanduser(os.environ["SPELLBOOK_APP_DIR"]))
    if configured:
        return os.path.abspath(os.path.expanduser(configured))
    legacy = os.path.join(app_root(), ".beta-data")
    if os.path.isdir(legacy):  # dev checkouts keep their in-repo data
        return legacy
    fallback = os.path.expanduser("~/Library/Application Support/Spellbook") if sys.platform == "darwin" \
        else os.path.expanduser("~/.local/share/Spellbook")
    return fallback


def documents_dir():
    """User's Documents folder, per-OS (XDG envs honored on Linux)."""
    if sys.platform.startswith("win"):
        base = os.environ.get("USERPROFILE", os.path.expanduser("~"))
        docs = os.path.join(base, "Documents")
    elif sys.platform == "darwin":
        docs = os.path.join(os.path.expanduser("~"), "Documents")
    else:
        docs = os.environ.get("XDG_DOCUMENTS_DIR") or os.path.join(
            os.environ.get("XDG_HOME_DIR") or os.path.expanduser("~"), "Documents")
    return os.path.expanduser(docs)


def library_dir():
    """Default library folder on a fresh machine (created on first use)."""
    return os.path.join(documents_dir(), "Spellbook UI", "Library")


def forge_dir():
    """Developer/Forge install root (overwrite via installer config)."""
    return _pick("SPELLBOOK_FORGE", "forge_dir", "~/stable-diffusion-webui-forge")


def pose_kit_dir():
    return _pick("SPELLBOOK_POSE_KIT", "pose_kit_dir", os.path.join(app_root(), ".pose-kit"))


def krita_styles_dir():
    """Krita AI Diffusion style presets, per-OS (override in spellbook.json)."""
    if sys.platform == "darwin":
        default = "~/Library/Application Support/krita/ai_diffusion/styles"
    elif sys.platform.startswith("win"):
        default = "~/AppData/Roaming/krita/ai_diffusion/styles"
    else:
        default = "~/.local/share/krita/ai_diffusion/styles"
    return _pick("SPELLBOOK_KRITA_STYLES", "krita_styles_dir", default)


def protected_paths():
    """Directories never to write into (e.g. a prior install's data on this machine).

    Empty by default: a clean build has nothing to protect. Environments that do
    list them explicitly in ``spellbook.json`` under ``original_protected_paths``."""
    configured = _config().get("original_protected_paths")
    if isinstance(configured, list) and configured:
        return tuple(os.path.abspath(os.path.expanduser(p)) for p in configured)
    return ()


def write_config_template():
    """Drop a spellbook.json next to the app (first run) so operators can see what is movable.

    Keys left as null keep their defaults; the idle machine's config will stay untouched."""
    path = config_path()
    if os.path.exists(path):
        return False
    template = {
        "_readme": ("Spellbook path configuration. Replace null values with absolute paths "
                    "to move robust parts of the app; delete the file entirely to use defaults."),
        "app_data_dir": None,
        "forge_dir": None,
        "pose_kit_dir": None,
        "krita_styles_dir": None,
        "original_protected_paths": None,
    }
    try:
        with open(path, "w") as f:
            json.dump(template, f, indent=2)
    except OSError:
        return False
    return True
