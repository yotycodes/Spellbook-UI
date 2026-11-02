"""AI Prompt Bridge — tiny local HTTP endpoint so the Prompt Library app can fill Krita AI Diffusion's prompt.

POST http://127.0.0.1:8767/prompt  {"prompt": "...", "negative": "...", "style": "Toon · Pin-up"}
POST http://127.0.0.1:8767/pose    {"path": "/…/pinup_side_adult.png", "name": "Pin-up · side"}  -> hidden layer + Pose control
POST http://127.0.0.1:8767/image   {"path": "/…/ref.jpg", "name": "Ref", "modes": ["reference", "pose"]}
                                    -> hidden image layer + one control per mode (pose/depth/line art are extracted)
POST http://127.0.0.1:8767/open    {"path": "/…/image.png"}  -> opens the image as a new Krita document
GET  http://127.0.0.1:8767/ping    -> {"ok": true, "document": bool}
Localhost only. Kept separate from ai_diffusion so plugin updates don't remove it."""
import json

from krita import Extension, Krita
from PyQt5.QtCore import QTimer
from PyQt5.QtNetwork import QHostAddress, QTcpServer

PORT = 8767


def _apply(data):
    from ai_diffusion.model.root import root
    from ai_diffusion.style import Styles

    model = root.active_model
    if model is None or Krita.instance().activeDocument() is None:
        return {"ok": False, "error": "Open a document in Krita first."}
    note = ""
    name = (data.get("style") or "").strip()
    if name:
        style = next((s for s in Styles.list() if s.name == name), None)
        if style is None:  # allow partial names, e.g. "Curvy · Toon"
            style = next((s for s in Styles.list() if name.lower() in s.name.lower()), None)
        if style is not None:
            model.style = style
        else:
            note = f"style '{name}' not found — kept current style"
    if "prompt" in data:
        model.regions.positive = data.get("prompt") or ""
    if data.get("negative"):
        model.regions.negative = data["negative"]
    return {"ok": True, "style": model.style.name, "note": note}


def _add_pose(data):
    import os
    from ai_diffusion.backend.resources import ControlMode
    from ai_diffusion.image import Bounds, Extent, Image
    from ai_diffusion.model.root import root

    model = root.active_model
    doc = Krita.instance().activeDocument()
    if model is None or doc is None:
        return {"ok": False, "error": "Open a document in Krita first."}
    path = data.get("path") or ""
    if not os.path.isfile(path):
        return {"ok": False, "error": f"skeleton not found: {path}"}
    w, h = doc.width(), doc.height()
    img = Image.scale_to_fit(Image.load(path), Extent(w, h))
    x, y = (w - img.width) // 2, (h - img.height) // 2
    if (x, y) != (0, 0):  # letterbox onto a black canvas so the pose stays centred and undistorted
        canvas = Image.create(Extent(w, h), fill=0xFF000000) if hasattr(Image, "create") else None
        if canvas is not None:
            canvas.draw_image(img, (x, y))
            img, x, y = canvas, 0, 0
    name = "Pose · " + (data.get("name") or os.path.splitext(os.path.basename(path))[0])
    layer = model.layers.create(name, img, Bounds(x, y, img.width, img.height), make_active=True)
    model.regions.control.add()
    control = model.regions.control[-1]
    control.mode = ControlMode.pose
    layer.hide()
    note = "" if (img.width, img.height) == (w, h) else f"canvas {w}×{h} differs from the skeleton — fitted"
    return {"ok": True, "layer": name, "controls": len(model.regions.control), "note": note}


_EXTRACT = {"pose", "depth", "line_art", "canny_edge", "soft_edge", "scribble", "normal"}


def _add_image(data):
    import os
    from ai_diffusion.backend.resources import ControlMode
    from ai_diffusion.image import Bounds, Extent, Image
    from ai_diffusion.model.root import root

    model = root.active_model
    doc = Krita.instance().activeDocument()
    if model is None or doc is None:
        return {"ok": False, "error": "Open a document in Krita first."}
    path = data.get("path") or ""
    if not os.path.isfile(path):
        return {"ok": False, "error": f"image not found: {path}"}
    w, h = doc.width(), doc.height()
    img = Image.scale_to_fit(Image.load(path), Extent(w, h))
    x, y = (w - img.width) // 2, (h - img.height) // 2
    name = data.get("name") or os.path.splitext(os.path.basename(path))[0]
    layer = model.layers.create(name, img, Bounds(x, y, img.width, img.height), make_active=True)
    added, notes = [], []
    for m in data.get("modes") or []:
        mode = getattr(ControlMode, m, None)
        if mode is None:
            notes.append(f"unknown mode {m}")
            continue
        model.layers.active = layer
        model.regions.control.add()
        control = model.regions.control[-1]
        control.mode = mode
        added.append(m)
        if m in _EXTRACT:
            if getattr(control, "can_generate", False):
                control.generate()  # Krita's preprocessor makes the pose/depth/lines layer from the image
            else:
                notes.append(f"{m}: not available for this style's model — kept the image as the control")
    if data.get("modes"):
        layer.hide()
    return {
        "ok": True,
        "layer": name,
        "modes": added,
        "note": "; ".join(notes),
        "doc_name": doc.name() if hasattr(doc, "name") else None,
        "doc_size": [doc.width(), doc.height()],
    }


def _open_doc(data):
    import os
    path = data.get("path") or ""
    if not os.path.isfile(path):
        return {"ok": False, "error": f"image not found: {path}"}
    app = Krita.instance()
    doc = app.openDocument(path)
    if doc is None:
        return {"ok": False, "error": "Krita couldn't open the image"}
    win = app.activeWindow() or (app.windows()[0] if app.windows() else None)
    if win is not None:
        win.addView(doc)
    return {
        "ok": True,
        "name": os.path.basename(path),
        "size": [doc.width(), doc.height()],
        "resolution": doc.resolution() if hasattr(doc, "resolution") else None,
        "color_depth": doc.colorDepth() if hasattr(doc, "colorDepth") else None,
    }


class AIPromptBridge(Extension):
    def __init__(self, parent):
        super().__init__(parent)
        self.server = None

    def setup(self):
        QTimer.singleShot(3000, self._start)  # give ai_diffusion time to load

    def createActions(self, window):
        pass

    def _start(self):
        self.server = QTcpServer()
        self.server.newConnection.connect(self._on_conn)
        if not self.server.listen(QHostAddress.LocalHost, PORT):
            print(f"[AI Prompt Bridge] could not listen on {PORT}")

    def _on_conn(self):
        sock = self.server.nextPendingConnection()
        sock.setProperty("buf", b"")
        sock.readyRead.connect(lambda s=sock: self._read(s))

    def _read(self, sock):
        buf = bytes(sock.property("buf") or b"") + bytes(sock.readAll())
        sock.setProperty("buf", buf)
        head, sep, body = buf.partition(b"\r\n\r\n")
        if not sep:
            return
        lines = head.decode("latin-1").split("\r\n")
        method, path = (lines[0].split(" ") + ["", ""])[:2]
        length = next((int(l.split(":", 1)[1]) for l in lines[1:] if l.lower().startswith("content-length:")), 0)
        if len(body) < length:
            return
        try:
            if method == "GET" and path.startswith("/ping"):
                doc = Krita.instance().activeDocument()
                res = {
                    "ok": True,
                    "document": doc is not None,
                    "doc_name": doc.name() if doc else None,
                    "size": [doc.width(), doc.height()] if doc else None,
                }
            elif method == "POST" and path.startswith("/open"):
                res = _open_doc(json.loads(body[:length].decode("utf-8") or "{}"))
            elif method == "POST" and path.startswith("/image"):
                res = _add_image(json.loads(body[:length].decode("utf-8") or "{}"))
            elif method == "POST" and path.startswith("/pose"):
                res = _add_pose(json.loads(body[:length].decode("utf-8") or "{}"))
            elif method == "POST" and path.startswith("/prompt"):
                res = _apply(json.loads(body[:length].decode("utf-8") or "{}"))
            else:
                res = {"ok": False, "error": "unknown endpoint"}
        except Exception as e:
            res = {"ok": False, "error": f"{e.__class__.__name__}: {e}"}
        out = json.dumps(res).encode()
        sock.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(out) + out)
        sock.flush()
        sock.disconnectFromHost()


Krita.instance().addExtension(AIPromptBridge(Krita.instance()))
