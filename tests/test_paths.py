import getpass
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "standalone"))
import paths  # noqa: E402


def _clean_env(monkeypatch):
    for key in ("SPELLBOOK_ROOT", "SPELLBOOK_APP_DIR", "SPELLBOOK_FORGE",
                "SPELLBOOK_POSE_KIT", "SPELLBOOK_KRITA_STYLES"):
        monkeypatch.delenv(key, raising=False)
    paths.reset_cache()


def _root(monkeypatch, tmp_path, platform="darwin"):
    """Point paths at an isolated fake app root and fake the OS."""
    _clean_env(monkeypatch)
    monkeypatch.setenv("SPELLBOOK_ROOT", str(tmp_path))
    monkeypatch.setattr(paths.sys, "platform", platform if platform else sys.platform)
    paths.reset_cache()


def test_dev_checkout_keeps_legacy_data_dir(tmp_path, monkeypatch):
    _root(monkeypatch, tmp_path)
    (tmp_path / ".beta-data").mkdir()
    assert paths.app_data_dir() == str(tmp_path / ".beta-data")


def test_fresh_machine_gets_platform_data_dir(tmp_path, monkeypatch):
    _root(monkeypatch, tmp_path, platform="darwin")
    home = os.path.expanduser("~")
    assert paths.app_data_dir() == os.path.join(home, "Library", "Application Support", "Spellbook")


def test_linux_machine_gets_xdg_style_dir(tmp_path, monkeypatch):
    _root(monkeypatch, tmp_path, platform="linux")
    assert paths.app_data_dir() == os.path.expanduser("~/.local/share/Spellbook")


def test_config_file_overrides_defaults(tmp_path, monkeypatch):
    (tmp_path / "spellbook.json").write_text('{"app_data_dir": "~/ElsewhereData", "forge_dir": "~/MyForge"}')
    _root(monkeypatch, tmp_path, platform="linux")
    paths.reset_cache()
    assert paths.app_data_dir() == os.path.expanduser("~/ElsewhereData")
    assert paths.forge_dir() == os.path.expanduser("~/MyForge")


def test_env_beats_config(tmp_path, monkeypatch):
    (tmp_path / "spellbook.json").write_text('{"app_data_dir": "~/FromConfig"}')
    _root(monkeypatch, tmp_path, platform="linux")
    paths.reset_cache()
    monkeypatch.setenv("SPELLBOOK_APP_DIR", str(tmp_path / "from-env"))
    assert paths.app_data_dir() == str(tmp_path / "from-env")


def test_protected_paths_are_config_only(tmp_path, monkeypatch):
    """Clean builds ship no protected paths; environments that need one list it in spellbook.json."""
    _root(monkeypatch, tmp_path, platform="darwin")
    assert paths.protected_paths() == ()
    _root(monkeypatch, tmp_path, platform="linux")
    assert paths.protected_paths() == ()
    (tmp_path / "spellbook.json").write_text('{"original_protected_paths": ["/srv/original-data"]}')
    paths.reset_cache()
    assert paths.protected_paths() == ("/srv/original-data",)


def test_config_template_written_once(tmp_path, monkeypatch):
    _root(monkeypatch, tmp_path, platform="linux")
    assert paths.write_config_template() is True
    content = open(tmp_path / "spellbook.json").read()
    assert "app_data_dir" in content and paths.write_config_template() is False


def test_sources_have_no_historical_hardcode():
    """Ensure no user- or machine-specific paths in app source."""
    root = os.path.join(os.path.dirname(__file__), "..")
    user = getpass.getuser()
    banned = (f"/Users/{user}", "Desktop/Spellbook")
    skipped = {"test_paths.py"}       # self-referential: contains the ban list itself
    shells = {"SpellbookUILauncher.swift"}  # platform shell; its default falls back to env override
    for sub in ("standalone", "lib_pl", "tests"):
        for name in os.listdir(os.path.join(root, sub)):
            if not name.endswith((".py", ".js", ".css", ".html", ".swift", ".sh")):
                continue
            if name in skipped or name in shells:
                continue
            text = open(os.path.join(root, sub, name), encoding="utf-8", errors="ignore").read()
            for ban in banned:
                assert ban not in text, f"{sub}/{name} hardcodes {ban}"
