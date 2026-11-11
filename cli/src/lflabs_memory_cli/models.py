"""The local models (spec 10.2): listed in the engine's models.json (built by `python -m lflabs_memory.models
FOLDER RELEASE`) with URL, size and sha256; downloaded into
DATA_DIR/models/<name>/ and refused when a checksum differs.

models.json: {"release": "models-<date>", "models": {"embed": [{"file", "url", "size", "sha256"}], ...}}
"""
import hashlib
import http.client
import json
import os
import time
import tomllib
import urllib.request
from importlib import resources
from pathlib import Path

from .layout import data_dir

MODELS_ENV = "LFLABS_MEMORY_MODELS"  # the engine reads it first too (config.load)
OPTIONAL = ("sense",)  # without it the word lists decide (spec 10.2)
# Chinese and Japanese only (engine 0.1.9): never in setup or update. The engine asks for them the first time it sees
# Chinese or Japanese text, by running `models --get` (get below) in the background; until then its CJK word rules
# decide. Their state, for doctor and for the engine's next ask: data_dir()/models-ml.json.
LAZY = ("embed-ml", "rerank-ml")


def manifest():
    """The engine's models.json, or None when the engine (or its list) is not installed."""
    try:
        return json.loads((resources.files("lflabs_memory") / "models.json").read_text())
    except (ModuleNotFoundError, FileNotFoundError, OSError, ValueError):
        return None


def folder():
    """Where the engine looks for models: LFLABS_MEMORY_MODELS, else config.toml's `models`, else DATA_DIR/models."""
    got = os.environ.get(MODELS_ENV)
    try:
        got = got or tomllib.loads((data_dir() / "config.toml").read_text()).get("models")
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


class DownloadError(OSError):
    """Some models could not be downloaded (each file tried TRIES times): missing is {model name: why}. What was got of
    a file is kept (<file>.part), so the next try goes on from there."""

    def __init__(self, missing):
        super().__init__(", ".join(f"{n}: {why}" for n, why in missing.items()))
        self.missing = missing


TRIES = 5


def total_size(man, names):
    return sum(f["size"] for n in names for f in man["models"][n])


def _get(f, part, opener, progress):
    """Append to part from where it ends (a Range request; a server that answers 200 sends it all again). Raises
    OSError on a dropped connection or a short file."""
    have = part.stat().st_size if part.exists() else 0
    req = urllib.request.Request(f["url"], headers={"Range": f"bytes={have}-"} if have else {})
    with opener(req, timeout=60) as r:
        resumed = bool(have) and getattr(r, "status", None) == 206
        n = have if resumed else 0
        with open(part, "ab" if resumed else "wb") as out:
            while chunk := r.read(1 << 16):
                out.write(chunk)
                n += len(chunk)
                progress(n)
    if n != f["size"]:
        raise OSError(f"got {n} of {f['size']} bytes")


def lazy_state():
    try:
        got = json.loads((data_dir() / "models-ml.json").read_text())
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(st):
    p = data_dir() / "models-ml.json"
    tmp = p.with_name(f"models-ml.json.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(st))
    os.replace(tmp, p)


def get(names, say=print, opener=None, sleep=None):
    """`models --get`: download these models now (what the engine runs in the background for LAZY), one run at a
    time (a lock in the data folder: a second run waits, then finds them there). Records how it went in
    models-ml.json (state ok | failed, why, at), keeping the engine's "asked". 0 when they are all here and match."""
    import fcntl
    man = manifest()
    if man is None:
        say("The engine has no models list: reinstall with the install line.")
        return 1
    unknown = [n for n in names if n not in man["models"]]
    if unknown:
        say(f"No such model: {', '.join(unknown)}")
        return 2
    data_dir().mkdir(parents=True, exist_ok=True)
    with open(data_dir() / "models-ml.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        todo = [n for n, s in check(man, names=names).items() if s != "ok"]
        st = lazy_state()
        if todo:
            say(f"Downloading {', '.join(todo)} ({total_size(man, todo) / 1e6:.0f} MB)...")
            try:
                download(man, todo, opener=opener, sleep=sleep)
            except (ChecksumError, OSError) as e:
                st.update(state="failed", why=str(e)[:300], at=time.time())
                _write_state(st)
                say(f"Not downloaded ({e}). The next Chinese or Japanese text tries again in a few hours.")
                return 1
        st.update(state="ok", why="", at=time.time())
        _write_state(st)
        say(f"{', '.join(names)}: here, checksums match")
        return 0


def download(man, names, progress=lambda done, total: None, where=None, opener=None, sleep=None, tries=TRIES):
    """Fetch every file of `names` that is missing or wrong: each tried `tries` times, waiting 1, 2, 4... s, and
    resumed where it stopped. A file whose size or sha256 does not match is deleted: nothing unchecked is ever put in
    place. After trying them all: ChecksumError if one did not match, else DownloadError if one could not be got."""
    opener, sleep, where = opener or urllib.request.urlopen, sleep or time.sleep, where or folder()
    todo = [(n, f) for n in names for f in man["models"][n]
            if not ((where / n / f["file"]).exists() and file_sha256(where / n / f["file"]) == f["sha256"])]
    total = sum(f["size"] for _, f in todo) or 1
    done, missing, bad = 0, {}, []
    progress(0, total)
    for name, f in todo:
        dest = where / name / f["file"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        if part.exists() and part.stat().st_size > f["size"]:
            part.unlink()
        base = done
        for attempt in range(tries):
            try:
                _get(f, part, opener, lambda n: progress(base + n, total))
                break
            except (OSError, http.client.HTTPException) as e:
                why = str(e) or type(e).__name__
                if attempt + 1 < tries:
                    sleep(2 ** attempt)
        else:
            missing.setdefault(name, why)
            continue
        if part.stat().st_size != f["size"] or file_sha256(part) != f["sha256"]:
            part.unlink(missing_ok=True)
            bad.append(f"{name}/{f['file']}")
            continue
        os.replace(part, dest)
        done = base + f["size"]
    progress(total, total)
    if bad:
        raise ChecksumError(f"{', '.join(bad)} did not match its checksum: deleted")
    if missing:
        raise DownloadError(missing)
    return done
