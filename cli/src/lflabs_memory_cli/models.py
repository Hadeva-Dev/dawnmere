"""The local models (spec 10.2): listed in the engine's models.json (built by `python -m lflabs_memory.models
FOLDER RELEASE`) with URL, size and sha256; downloaded into
DATA_DIR/models/<name>/ and refused when a checksum differs.

models.json: {"release": "models-<date>", "models": {"embed": [{"file", "url", "size", "sha256"}], ...}}
"""
import hashlib
import json
import os
import tomllib
import urllib.request
from importlib import resources
from pathlib import Path

from .layout import data_dir

OPTIONAL = ("sense",)  # without it the word lists decide (spec 10.2)


def manifest():
    """The engine's models.json, or None when the engine (or its list) is not installed."""
    try:
        return json.loads((resources.files("lflabs_memory") / "models.json").read_text())
    except (ModuleNotFoundError, FileNotFoundError, OSError, ValueError):
        return None


def folder():
    """Where the engine looks for models: config.toml's `models`, else DATA_DIR/models."""
    try:
        got = tomllib.loads((data_dir() / "config.toml").read_text()).get("models")
    except (OSError, tomllib.TOMLDecodeError):
        got = None
    return Path(got).expanduser() if got else data_dir() / "models"


def file_sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


def check(man, where=None, names=None):
    """{model name: "ok" | "missing" | "mismatch"} for each model in the list (or `names`)."""
    where = where or folder()
    out = {}
    for name, files in man["models"].items():
        if names and name not in names:
            continue
        state = "ok"
        for f in files:
            p = where / name / f["file"]
            if not p.exists():
                state = "missing"
                break
            if p.stat().st_size != f["size"] or file_sha256(p) != f["sha256"]:
                state = "mismatch"
                break
        out[name] = state
    return out


class ChecksumError(RuntimeError):
    pass


def total_size(man, names):
    return sum(f["size"] for n in names for f in man["models"][n])


def download(man, names, progress=lambda done, total: None, where=None, opener=urllib.request.urlopen):
    """Fetch every file of `names` that is missing or wrong, checking size and sha256 while it streams. A file that
    does not match is deleted and ChecksumError raised: nothing half-downloaded is ever left in place."""
    where = where or folder()
    todo = [(n, f) for n in names for f in man["models"][n]
            if not ((where / n / f["file"]).exists() and file_sha256(where / n / f["file"]) == f["sha256"])]
    total = sum(f["size"] for _, f in todo) or 1
    done = 0
    progress(0, total)
    for name, f in todo:
        dest = where / name / f["file"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        h = hashlib.sha256()
        try:
            with opener(f["url"], timeout=60) as r, open(part, "wb") as out:
                while chunk := r.read(1 << 16):
                    out.write(chunk)
                    h.update(chunk)
                    done += len(chunk)
                    progress(done, total)
            if part.stat().st_size != f["size"] or h.hexdigest() != f["sha256"]:
                raise ChecksumError(f"{name}/{f['file']} did not match its checksum: deleted")
            os.replace(part, dest)
        finally:
            part.unlink(missing_ok=True)
    progress(total, total)
    return done
