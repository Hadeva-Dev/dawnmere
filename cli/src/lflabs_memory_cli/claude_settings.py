"""~/.claude/settings.json around the plugin commands.

Claude Code rewrites the file whenever it runs (seen on 2.1.301 in a throwaway home: a bare `claude plugin list`
reordered the keys and turned "model": "opus" into "opus[1m]"), the plugin commands add an extraKnownMarketplaces and an
enabledPlugins entry, and uninstalling leaves both behind as empty tables; the plugin's cached copy stays in
~/.claude/plugins/cache. So setup keeps a copy of the file before its first `claude` command, and uninstall, after its
own plugin commands, puts that copy back when nothing but those changes happened since, else takes out only what the
plugin added (and the empty tables it left).
"""
import json
import os
import shutil

from . import apps, edits
from .layout import MARKETPLACE, OLD_MARKETPLACE, OLD_SERVER, REPO_DIR, SERVER, data_dir, home

PLUGIN_ID = f"{SERVER}@{MARKETPLACE}"
OLD_PLUGIN_ID = f"{OLD_SERVER}@{OLD_MARKETPLACE}"  # before 0.1.10: setup and update move it to PLUGIN_ID
OURS = (("enabledPlugins", PLUGIN_ID), ("extraKnownMarketplaces", MARKETPLACE),
        ("enabledPlugins", OLD_PLUGIN_ID), ("extraKnownMarketplaces", OLD_MARKETPLACE))


def path():
    return home() / ".claude/settings.json"


def plugins_dir():
    return home() / ".claude/plugins"


def snapshot_file():
    return data_dir() / "claude-settings-before.json"


def snapshot():
    """Keep the file as it is before setup's first `claude` command (once: a rerun keeps the first copy). 0600, in the
    owner-only data folder: settings.json can hold secrets."""
    snap = snapshot_file()
    if snap.exists():
        return
    try:
        text = edits.read(path())
    except edits.Skip:
        return
    ours = text is not None and (any(f'"{name}"' in text for _, name in OURS) or "hook-prompt" in text)
    doc = {"existed": text is not None, "text": None if ours else text, "plugins_dir": plugins_dir().exists()}
    snap.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with os.fdopen(os.open(snap, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        json.dump(doc, f)


def _load_snapshot():
    try:
        return json.loads(snapshot_file().read_text())
    except (OSError, ValueError):
        return None


def strip(data, before=None):
    """data without the plugin's entries and the tables they leave empty that `before` did not have. (Our fallback
    hooks are uninstall's file step's, which can put the file back byte for byte.)"""
    new = json.loads(json.dumps(data))
    for key, name in OURS:
        table = new.get(key)
        if isinstance(table, dict):
            table.pop(name, None)
            if not table and not (isinstance(before, dict) and key in before):
                del new[key]
    return new


def _model(v):
    return v.split("[", 1)[0] if isinstance(v, str) else v  # "opus[1m]" is Claude Code's own rewrite of "opus"


def same(a, b):
    """Equal but for key order and Claude Code's model rewrite."""
    if not (isinstance(a, dict) and isinstance(b, dict)):
        return a == b
    return {**a, "model": _model(a.get("model"))} == {**b, "model": _model(b.get("model"))}


def put_back():
    """After uninstall's plugin commands: the file as it was before setup when nothing else changed, else without
    what the plugin added; then the plugin's cached copy goes. A note for the report, or None."""
    snap = _load_snapshot()
    note = None
    try:
        text = edits.read(path())
        cur = edits.load_json(text) if text is not None else None
    except edits.Skip:
        text = cur = None
    if cur is not None:
        before = edits.load_json(snap["text"]) if snap and snap.get("text") else None
        stripped = strip(cur, before)
        bare = apps._drop_hooks(stripped)[0]
        try:
            if before is not None and same(bare, before):
                if text != snap["text"]:
                    edits.write(path(), snap["text"], text, backup=False)
                    note = "~/.claude/settings.json: put back as it was"
            elif snap and not snap.get("existed") and apps.empty_structure(bare, ()):
                edits.write(path(), None, text, backup=False)
                note = "~/.claude/settings.json: removed (it did not exist before setup)"
            elif stripped != cur:
                edits.write(path(), edits.dump_json(stripped, text), text, backup=False)
                note = "~/.claude/settings.json: the plugin's entries taken out"
        except edits.Skip as e:
            note = f"~/.claude/settings.json: {e}"
    _drop_plugin_files(snap)
    snapshot_file().unlink(missing_ok=True)
    return note


def _drop_plugin_files(snap):
    """The plugin's cached copy and its marketplace's checkout, which `claude plugin uninstall` and `marketplace remove`
    leave behind; and ~/.claude/plugins itself when setup made it and only Claude Code's empty bookkeeping is left."""
    pd = plugins_dir()
    for pattern in [p for m in (MARKETPLACE, OLD_MARKETPLACE) for p in (f"cache/{m}", f"cache/{m}-*",
                                                                         f"marketplaces/{m}", f"marketplaces/{m}-*")] + \
            [f"marketplaces/{REPO_DIR}", f"marketplaces/{REPO_DIR}-*"]:
        for p in pd.glob(pattern):
            shutil.rmtree(p, ignore_errors=True)
    if not snap or snap.get("plugins_dir") or not pd.is_dir():
        return
    for p in pd.rglob("*"):
        if p.is_file():
            try:
                if not apps.empty_structure(json.loads(p.read_text())):
                    return
            except (OSError, ValueError):
                return
    shutil.rmtree(pd, ignore_errors=True)
