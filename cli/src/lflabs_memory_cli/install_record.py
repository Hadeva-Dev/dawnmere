"""DATA_DIR/install.json: everything setup changed, so uninstall can put it back (spec 9.2).

{"version": 1,
 "files": [{"app", "kind", "path", "backup", "added", "created", "sha256"}],   sha256: the file as setup left it
 "commands": [{"argv": [...], "ok": true}],                                      plugin, marketplace, launchctl
 "keychain": false, "plist": "~/Library/LaunchAgents/com.lflabs.memory.plist",
 "versions": {"cli": ..., "engine": ..., "connector": ...}}
"""
import json
import os
import time

from .layout import install_json


def load():
    """The record, or None when there is none (or it cannot be read: uninstall then looks for itself)."""
    try:
        data = json.loads(install_json().read_text())
        return data if isinstance(data, dict) and data.get("version") == 1 else None
    except (OSError, ValueError):
        return None


def empty():
    return {"version": 1, "created": time.time(), "files": [], "commands": [], "keychain": False, "plist": None,
            "versions": {}}


def save(record):
    path = install_json()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(path.name + ".tmp")
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        json.dump(record, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def add_file(record, plan, backup, sha256):
    """One changed file. A rerun that changes the same file again keeps the first backup (the user's original)."""
    prev = next((f for f in record["files"] if f["path"] == str(plan.path) and f["kind"] == plan.kind), None)
    entry = {"app": plan.app, "kind": plan.kind, "path": str(plan.path),
             "backup": prev["backup"] if prev else (str(backup) if backup else None),
             "created": prev["created"] if prev else plan.old is None,
             "added": plan.added, "sha256": sha256}
    if prev:
        record["files"][record["files"].index(prev)] = entry
    else:
        record["files"].append(entry)


def add_command(record, argv, ok):
    record["commands"].append({"argv": list(argv), "ok": bool(ok), "at": time.time()})
