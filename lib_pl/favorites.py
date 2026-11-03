"""Favorites: named collections of library prompt ids + per-prompt notes, stored as one JSON file."""
import json
import os
import threading


class Favorites:
    DEFAULT = "⭐ Favorites"

    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self.data = {"collections": {self.DEFAULT: []}, "notes": {}}
        try:
            with open(path) as f:
                d = json.load(f)
            self.data["collections"].update(d.get("collections", {}))
            self.data["notes"].update(d.get("notes", {}))
        except (OSError, ValueError):
            pass

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.data, f, indent=1, ensure_ascii=False)
        os.replace(tmp, self.path)

    def names(self):
        return list(self.data["collections"])

    def ids(self, name):
        return set(self.data["collections"].get(name, []))

    def add(self, name, rid, note=None):
        name = (name or self.DEFAULT).strip() or self.DEFAULT
        with self._lock:
            lst = self.data["collections"].setdefault(name, [])
            if rid not in lst:
                lst.append(rid)
            if note is not None:
                if note.strip():
                    self.data["notes"][str(rid)] = note.strip()
                else:
                    self.data["notes"].pop(str(rid), None)
            self._save()
        return name

    def remove(self, name, rid):
        with self._lock:
            lst = self.data["collections"].get(name, [])
            if rid in lst:
                lst.remove(rid)
                self._save()

    def note(self, rid):
        return self.data["notes"].get(str(rid), "")

    def clear(self):
        """Wipe collections + notes back to a fresh state. Returns the number of ids that were collected."""
        with self._lock:
            ids = set()
            for lst in self.data["collections"].values():
                ids.update(lst)
            ids.update(int(k) for k in self.data["notes"] if str(k).lstrip("-").isdigit())
            self.data = {"collections": {self.DEFAULT: []}, "notes": {}}
            self._save()
            return len(ids)

    def where(self, rid):
        return [n for n, l in self.data["collections"].items() if rid in l]
