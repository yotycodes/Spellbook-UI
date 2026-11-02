"""Forge on/off switch: start webui.sh in the background, watch it come up, stop it again.

Forge started here runs detached (its own session) and logs to forge.log in the app folder, so it survives
the Prompt Library window closing. Stop works for a Forge started anywhere: it signals whatever listens on the port."""
import os
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from fastapi import APIRouter, Body

router = APIRouter(prefix="/api/forge")
CFG = {"forge_dir": "", "forge_url": "http://127.0.0.1:7860", "log": ""}
READ_ONLY = False  # Beta is the primary app and owns Forge start/stop; Original is the recovery copy.
_proc = {"p": None, "started": 0.0, "stopping": False, "log_f": None}
_lock = threading.Lock()


def configure(forge_dir, forge_url, log_path):
    CFG.update(forge_dir=forge_dir, forge_url=forge_url.rstrip("/"), log=log_path)


def _port():
    return urllib.parse.urlparse(CFG["forge_url"]).port or 7860


def _listening(port):
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _api_state():
    try:
        with urllib.request.urlopen(f"{CFG['forge_url']}/sdapi/v1/progress?skip_current_image=true", timeout=2.5):
            return "on"
    except urllib.error.HTTPError:
        return "no-api"
    except Exception:
        if _listening(_port()):
            return "busy"
        return "off"


def _log_tail(n=1):
    try:
        with open(CFG["log"], "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 4000))
            lines = [l.strip() for l in f.read().decode("utf-8", "replace").replace("\r", "\n").split("\n") if l.strip()]
        return lines[-n:]
    except OSError:
        return []


def _friendly(line):
    l = line.lower()
    for key, msg in (("installing", "installing requirements…"), ("loading weights", "loading the model…"),
                     ("model loaded", "model loaded…"), ("running on local url", "almost ready…"),
                     ("startup time", "almost ready…"), ("launching web ui", "launching…"),
                     ("python ", "starting Python…"), ("version:", "checking setup…")):
        if key in l:
            return msg
    return "warming up…"


@router.get("/status")
def status():
    state = _api_state()
    with _lock:
        p = _proc["p"]
        alive = p is not None and p.poll() is None
        started, stopping = _proc["started"], _proc["stopping"]
    out = {"state": state, "online": state != "off", "api": state == "on", "managed": alive}
    if state == "off" and alive and not stopping:
        tail = _log_tail(1)
        out.update(state="starting", elapsed=time.time() - started, detail=_friendly(tail[0]) if tail else "warming up…")
    elif state == "off" and p is not None and not alive and not stopping and p.returncode not in (0, None, -15):
        out.update(state="crashed", detail=" ".join(_log_tail(2))[-300:])
    if stopping and state != "off":
        out["state"] = "stopping"
    return out


@router.post("/start")
def start(force: bool = Body(False, embed=True)):
    if READ_ONLY:
        return {"ok": False, "error": "Forge control is disabled in this Beta build."}
    with _lock:
        running = _proc["p"] is not None and _proc["p"].poll() is None
    if running or _api_state() != "off" or _listening(_port()):
        return {"ok": True, "already": True}
    script = os.path.join(CFG["forge_dir"], "webui.sh")
    if not os.path.exists(script):
        return {"ok": False, "error": f"Forge not found at {CFG['forge_dir']}"}
    log_path = CFG["log"]
    # reopen log for each start so the file descriptor is fresh and can be closed later
    log_f = open(log_path, "ab", buffering=0)
    try:
        log_f.write(f"\n===== Prompt Library started Forge {time.ctime()} =====\n".encode())
    except OSError:
        pass
    # SD_WEBUI_RESTARTING=1 makes webui.py skip its "open in browser" step (its only effect), so Forge started
    # from here stays headless; launching Forge yourself still follows its auto_launch_browser setting.
    env = dict(os.environ, PYTHONUNBUFFERED="1", SD_WEBUI_RESTARTING="1")
    for key in ("VIRTUAL_ENV", "VIRTUAL_ENV_PROMPT", "VIRTUAL_ENV_DISABLE_PROMPT"):
        env.pop(key, None)
    p = subprocess.Popen(["bash", script], cwd=CFG["forge_dir"], stdout=log_f, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True, env=env)
    with _lock:
        _proc.update(p=p, started=time.time(), stopping=False, log_f=log_f)
    return {"ok": True}


def _pids_on_port(port):
    try:
        out = subprocess.run(["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"], capture_output=True, text=True, timeout=5).stdout
        return [int(x) for x in out.split()]
    except Exception:
        return []


@router.post("/stop")
def stop():
    if READ_ONLY:
        return {"ok": False, "error": "Forge control is disabled in this Beta build."}
    with _lock:
        p = _proc["p"]
        _proc["stopping"] = True
    sent = False
    if p is not None and p.poll() is None:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            sent = True
        except (ProcessLookupError, PermissionError):
            pass
    for pid in _pids_on_port(_port()):  # Forge started outside the app
        try:
            os.kill(pid, signal.SIGTERM)
            sent = True
        except (ProcessLookupError, PermissionError):
            pass

    def _settle():
        for _ in range(40):
            if not _listening(_port()):
                break
            time.sleep(0.5)
        for pid in _pids_on_port(_port()):  # still up after 20 s: force it
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        with _lock:
            log_f = _proc.get("log_f")
            _proc.update(stopping=False, p=None, log_f=None)
            if log_f:
                try:
                    log_f.close()
                except OSError:
                    pass

    threading.Thread(target=_settle, daemon=True).start()
    return {"ok": sent, "error": "" if sent else "Forge isn't running."}
