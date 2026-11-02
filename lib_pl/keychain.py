"""API keys in the macOS Keychain (login keychain, via the `security` tool) instead of a plain settings file."""
import subprocess

ACCOUNT = "Spellbook"


def get(service):
    try:
        r = subprocess.run(["security", "find-generic-password", "-a", ACCOUNT, "-s", service, "-w"],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def set(service, secret):
    """Store (or replace) a secret; an empty secret deletes it. Returns True on success."""
    try:
        if not secret:
            subprocess.run(["security", "delete-generic-password", "-a", ACCOUNT, "-s", service],
                           capture_output=True, timeout=5)
            return True
        r = subprocess.run(["security", "add-generic-password", "-a", ACCOUNT, "-s", service, "-w", secret, "-U"],
                           capture_output=True, timeout=5)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
