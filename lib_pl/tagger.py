import csv
import os
import re
import threading

import numpy as np
from PIL import Image

KAOMOJI = {"0_0", "(o)_(o)", "+_+", "+_-", "._.", "<o>_<o>", "<|>_<|>", "=_=", ">_<", "3_3", "6_9", ">_o",
           "@_@", "^_^", "o_o", "u_u", "x_x", "|_|", "||_||"}

TAGGER_REPOS = {
    "wd-vit-tagger-v3": "SmilingWolf/wd-vit-tagger-v3",
    "wd-eva02-large-tagger-v3": "SmilingWolf/wd-eva02-large-tagger-v3",
}


def format_tag(name):
    if name in KAOMOJI:
        return name
    return name.replace("_", " ")


def escape_sd(tag):
    if tag in KAOMOJI:
        return tag
    return tag.replace("(", "\\(").replace(")", "\\)")


def escape_sd_text(text):
    return re.sub(r"(?<!\\)([()])", r"\\\1", text)


def preprocess(image, size):
    img = image.convert("RGBA")
    canvas = Image.new("RGBA", img.size, (255, 255, 255, 255))
    canvas.alpha_composite(img)
    img = canvas.convert("RGB")
    side = max(img.size)
    square = Image.new("RGB", (side, side), (255, 255, 255))
    square.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
    square = square.resize((size, size), Image.BICUBIC)
    arr = np.asarray(square, dtype=np.float32)[:, :, ::-1]  # RGB -> BGR
    return np.ascontiguousarray(arr[np.newaxis])


def download(model_name, dest_dir):
    repo = TAGGER_REPOS[model_name]
    local = os.path.join(dest_dir, model_name)
    model = os.path.join(local, "model.onnx")
    tags = os.path.join(local, "selected_tags.csv")
    # Reuse a complete local model without an unnecessary Hugging Face HTTPS check.
    if os.path.isfile(model) and os.path.isfile(tags):
        return model, tags
    from huggingface_hub import hf_hub_download
    model = hf_hub_download(repo, "model.onnx", local_dir=local)
    tags = hf_hub_download(repo, "selected_tags.csv", local_dir=local)
    return model, tags


class Tagger:
    def __init__(self, model_path, tags_csv, session=None):
        self.model_path = model_path
        self.session = session
        self._lock = threading.Lock()
        self.names, self.categories = [], []
        with open(tags_csv, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                self.names.append(row["name"])
                self.categories.append(int(row["category"]))

    def _session(self):
        if self.session is None:
            with self._lock:
                if self.session is None:
                    import onnxruntime as ort
                    sess = ort.InferenceSession(self.model_path, providers=["CPUExecutionProvider"])
                    self.session = sess
        return self.session

    def tag(self, image, general_threshold=0.35, character_threshold=0.85):
        sess = self._session()
        inp = sess.get_inputs()[0]
        size = inp.shape[1] if isinstance(inp.shape[1], int) else 448
        probs = sess.run(None, {inp.name: preprocess(image, size)})[0][0]
        rating, general, character = {}, [], []
        for name, cat, p in zip(self.names, self.categories, probs):
            p = float(p)
            if cat == 9:
                rating[name] = p
            elif cat == 4 and p >= character_threshold:
                character.append((format_tag(name), p))
            elif cat == 0 and p >= general_threshold:
                general.append((format_tag(name), p))
        general.sort(key=lambda x: -x[1])
        character.sort(key=lambda x: -x[1])
        return {"general": general, "character": character, "rating": rating}
