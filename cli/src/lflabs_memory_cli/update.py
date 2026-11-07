"""update: the newest release from GitHub, installed with its checksums checked (spec 9.6).

The only network call is GitHub's release API (and the release's own files). Two halves:
1. this (old) program fetches the release, checks each wheel against the release's SHA256SUMS and installs them with uv;
2. the newly installed program finishes (`update --finish FROM`): models whose checksum changed, the engine's schema
   migration on a stopped service with a snapshot first, the service restarted, the plugin and the connector pins
   updated. A failed migration puts the snapshot back and reinstalls the old release.
"""
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import time
import urllib.request
from importlib import metadata
from pathlib import Path

from . import apps, edits, launchd, models, prompt
from .brand import COMMAND, PRODUCT, REPO
from .layout import (CLI_DIST, CONNECTOR, CONNECTOR_VERSION, ENGINE_DIST, LABEL, SERVER, data_dir, engine_bin,
                     home, short)
from .run import run

API = f"https://api.github.com/repos/{REPO}/releases"


def vtuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "0")[:3])


def installed_version():
    try:
        return metadata.version(CLI_DIST)
    except metadata.PackageNotFoundError:
        return "0"


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": f"{CLI_DIST}/{installed_version()}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def release(tag=None, get=fetch):
    """The latest release (or one tag's): {"version", "notes", "assets": {name: url}}."""
    doc = json.loads(get(f"{API}/tags/{tag}" if tag else f"{API}/latest"))
    return {"version": doc["tag_name"].lstrip("v"), "notes": doc.get("body") or "",
            "assets": {a["name"]: a["browser_download_url"] for a in doc.get("assets", [])}}


def wheels(rel, get=fetch, where=None):
    """Download the release's CLI and engine wheels into `where`, each checked against SHA256SUMS. [cli, engine]
    paths. Raises RuntimeError on a missing file or a checksum that differs."""
    sums = {}
    if "SHA256SUMS" not in rel["assets"]:
        raise RuntimeError("the release has no SHA256SUMS")
    for line in get(rel["assets"]["SHA256SUMS"]).decode().splitlines():
        parts = line.split()
        if len(parts) == 2:
            sums[parts[1].lstrip("*")] = parts[0]
    out = []
    for prefix in ("lflabs_memory_cli-", "lflabs_memory_engine-"):
        name = next((n for n in rel["assets"] if n.startswith(prefix) and n.endswith(".whl")), None)
        if not name or name not in sums:
            raise RuntimeError(f"the release has no checked {prefix}*.whl")
        data = get(rel["assets"][name])
        if hashlib.sha256(data).hexdigest() != sums[name]:
            raise RuntimeError(f"{name} did not match its checksum: nothing was installed")
        p = Path(where) / name
        p.write_bytes(data)
        out.append(p)
    return out


def install_wheels(cli_whl, engine_whl):
    return run(["uv", "tool", "install", "--force", "--python", "3.12", str(cli_whl), "--with", str(engine_whl),
                "--with-executables-from", ENGINE_DIST], timeout=600)


def main(check_only=False, yes=False, say=print, get=fetch):
    have = installed_version()
    try:
        rel = release(get=get)
    except Exception:
        say("Could not reach GitHub to check for an update. Try again later.")
        return 1
    if vtuple(rel["version"]) <= vtuple(have):
        say(f"{PRODUCT} {have} is the newest.")
        return 0
    say(f"{PRODUCT} {rel['version']} is out (you have {have}).")
    for line in [x for x in rel["notes"].splitlines() if x.strip()][:5]:
        say(f"  {line}")
    if check_only:
        return 0
    if not prompt.yes_no("Update now?", True, assume=True if yes else None):
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        try:
            cli_whl, engine_whl = wheels(rel, get, tmp)
        except Exception as e:
            say(f"Update stopped: {e}")
            return 1
        r = install_wheels(cli_whl, engine_whl)
        if not r.ok:
            say(f"Update stopped: uv could not install it ({(r.err or r.out).strip()[:200]}). Nothing changed.")
            return 1
    # the new program finishes: its models list, its migrations, its connector version
    new = Path(engine_bin() or "").with_name(COMMAND) if engine_bin() else None
    argv = [str(new) if new and new.exists() else COMMAND, "update", "--finish", have]
    os.execvp(argv[0], argv)


def snapshot():
    """A consistent copy of the store before the migration (None when there is no store)."""
    src = data_dir() / "memory.db"
    if not src.exists():
        return None
    dst = data_dir() / "backup" / f"memory-{time.strftime('%Y-%m-%d-%H%M%S')}-before-update.db"
    dst.parent.mkdir(parents=True, exist_ok=True)
    a, b = sqlite3.connect(src), sqlite3.connect(dst)
    try:
        a.backup(b)
    finally:
        a.close()
        b.close()
    os.chmod(dst, 0o600)
    return dst


def put_back(snap):
    db = data_dir() / "memory.db"
    for extra in ("-wal", "-shm"):
        Path(str(db) + extra).unlink(missing_ok=True)
    a, b = sqlite3.connect(snap), sqlite3.connect(db)
    try:
        a.backup(b)
    finally:
        a.close()
        b.close()


def bump_pins(say):
    """Point Codex's and Cursor's entries at this version of the connector."""
    pin = f"{CONNECTOR}@{CONNECTOR_VERSION}"
    for path in (home() / ".codex/config.toml", home() / ".cursor/mcp.json"):
        try:
            old = edits.read(path)
        except edits.Skip:
            continue
        if not old or pin in old or f"{CONNECTOR}@" not in old:
            continue
        new = re.sub(re.escape(CONNECTOR) + r"@[0-9][\w.\-]*", pin, old)
        try:
            (edits.load_toml if path.suffix == ".toml" else edits.load_json)(new)
            edits.write(path, new, old)
            say(f"{short(path)}: connector now {CONNECTOR_VERSION}")
        except edits.Skip as e:
            say(f"{short(path)}: {e}")


def finish(old_version, say=print, get=fetch):
    """Run by the newly installed program. 0 when updated; 1 after a rollback."""
    man = models.manifest()
    if man:
        stale = [n for n, s in models.check(man).items() if s == "mismatch" or (s == "missing" and n not in
                                                                                 models.OPTIONAL)]
        if stale:
            try:
                models.download(man, stale)
                say(f"Models updated: {', '.join(stale)}")
            except Exception as e:
                say(f"Models not updated ({e}); {COMMAND} doctor will say what to do.")
    eng = engine_bin()
    run(["launchctl", "bootout", f"{launchd.domain()}/{LABEL}"], timeout=30)
    snap = snapshot()
    r = run([eng, "migrate"], timeout=900) if eng else None
    if r is None or not r.ok:
        say("The new version could not update your memory's format: putting everything back.")
        if snap:
            put_back(snap)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                old = release(f"v{old_version}", get)
                install_wheels(*wheels(old, get, tmp))
        except Exception as e:
            say(f"Could not reinstall {old_version} ({e}): run the install line again.")
        run(["launchctl", "bootstrap", launchd.domain(), str(launchd.plist_path())], timeout=30)
        say(f"Back on {old_version}; your memory is as it was" + (f" (snapshot: {short(snap)})." if snap else "."))
        return 1
    run(["launchctl", "bootstrap", launchd.domain(), str(launchd.plist_path())], timeout=30)
    run(["launchctl", "kickstart", "-k", f"{launchd.domain()}/{LABEL}"], timeout=30)
    if apps.installed("claude-code") and SERVER in run(["claude", "plugin", "list"], timeout=30).out:
        run(["claude", "plugin", "update", SERVER], timeout=120)
    bump_pins(say)
    say(f"{PRODUCT} is updated ({old_version} to {installed_version()}).")
    return 0
