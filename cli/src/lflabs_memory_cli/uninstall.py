"""uninstall: take out everything setup added (spec 9.4). Each step is fine with its thing already gone."""
import os
import shutil
import time
from pathlib import Path

from . import apps, claude_settings, edits, install_record, keychain, launchd, layout, prompt, sockets
from .brand import COMMAND
from .layout import (BACKUP_TAG, CLI_DIST, MARKETPLACE, SERVER, connector_sock, data_dir, engine_sock, home, logs_dir,
                     short, uv_bin)
from .run import run


class Report:
    def __init__(self, out):
        self.out, self.removed, self.gone, self.errors, self.backups = out, [], [], [], []
        self.said = set()  # files a row already told about (settings.json, by claude_settings.put_back)

    def row(self, what, state, note):
        self.out(f"{what:<21}{note}")
        {"removed": self.removed, "gone": self.gone, "error": self.errors}[state].append(what)


def _claude_plugin(record, rep):
    """The plugin and its marketplace, or the fallback's MCP entry. Only what setup ran (or, with no record, what
    `claude` says is there) is undone."""
    if not shutil.which("claude"):
        rep.row("Claude Code", "gone", "claude not found: nothing to remove there")
        return
    ran = [" ".join(c["argv"]) for c in (record or {}).get("commands", []) if c.get("ok")]
    listed = run(["claude", "plugin", "list"], timeout=30)
    has_plugin = any("plugin install" in c for c in ran) or (record is None and SERVER in listed.out)
    if has_plugin:
        a = run(["claude", "plugin", "uninstall", SERVER, "--scope", "user"], timeout=60)
        run(["claude", "plugin", "marketplace", "remove", MARKETPLACE], timeout=60)
        rep.row("Claude Code", "removed" if a.ok else "gone",
                "plugin removed" if a.ok else "plugin already removed")
    has_mcp = any("mcp add" in c for c in ran) or (record is None and run(
        ["claude", "mcp", "get", SERVER], timeout=30).ok)
    if has_mcp:
        a = run(["claude", "mcp", "remove", "--scope", "user", SERVER], timeout=30)
        rep.row("Claude Code", "removed" if a.ok else "gone",
                f"MCP entry {SERVER} removed" if a.ok else f"MCP entry {SERVER} already removed")
    if not has_plugin and not has_mcp:
        rep.row("Claude Code", "gone", "no plugin or MCP entry")
    note = claude_settings.put_back()  # after the commands, which rewrite it too
    if note:
        rep.row("Claude Code", "removed", note)
        rep.said.add(str(claude_settings.path()))


def _file(entry, rep):
    """One app file: put back from its backup while it still holds exactly what setup wrote, else take our entries
    out of it as it is now. Then the backups setup (or the engine's connect) made of it go, but for the user's
    original when the file could not be put back from it."""
    label = f"{apps.LABELS.get(entry.get('app'), entry.get('app', ''))}"
    path = Path(entry["path"])
    if entry.get("sha256"):
        try:
            now = edits.sha256(edits.read(path))
        except edits.Skip:
            now = None
        if now == entry["sha256"]:
            if entry.get("created"):
                path.unlink(missing_ok=True)
                _backups(path, None)
                return rep.row(label, "removed", f"{short(path)}: removed (setup created it)")
            if entry.get("backup") and edits.restore(path, entry["backup"], entry["sha256"]):
                _backups(path, None)
                return rep.row(label, "removed", f"{short(path)}: put back as it was")
    p = apps.unplan(entry)
    if p.state == "gone" and str(path) in rep.said:  # put back already, with its row: no second, "already gone" one
        _backups(path, None)
        return None
    if p.state in ("gone", "remove"):
        kept = _backups(path, entry.get("backup"))
        rep.backups += [str(kept)] if kept else []
    if p.state == "gone":
        return rep.row(label, "gone", f"{short(path)}: {p.note}")
    if p.state == "error":
        return rep.row(label, "error", f"{short(path)}: {p.note}; remove the {SERVER} entries by hand")
    try:
        edits.write(path, p.new, p.old, backup=False)
    except edits.Skip as e:
        return rep.row(label, "error", f"{short(path)}: {e}")
    rep.row(label, "removed", f"{short(path)}: {p.note}")


def _backups(path, original):
    """Delete the <file>.lflabs-backup-* copies next to path, keeping `original` (the copy of the file from before
    setup) when it is given, still there, and holds no key. The kept one's path, or None."""
    real = Path(os.path.realpath(path))
    keep = None
    for b in sorted(real.parent.glob(f"{real.name}.{BACKUP_TAG}-*")):
        try:
            holds_key = apps.KEY_ENV in b.read_text(errors="replace") or "_MEMORY_CLIENT_KEY" in b.read_text(
                errors="replace")
        except OSError:
            continue
        if original and str(b) == str(original) and not holds_key:
            keep = b
            continue
        b.unlink(missing_ok=True)
    return keep


def _zprofile(rep):
    """The PATH line install.sh put in ~/.zprofile (DATA_DIR/zprofile-line: "created" or "existing", then exactly
    what it appended): taken out, and the file too when install.sh made it and nothing else is in it."""
    rec = data_dir() / "zprofile-line"
    try:
        was, added = rec.read_text().split("\n", 1)
    except (OSError, ValueError):
        return
    path = home() / ".zprofile"
    try:
        old = edits.read(path)
        if old is not None and old.count(added) == 1:
            i = old.index(added)
            rest = old[i + len(added):]  # lines added since stay on lines of their own
            new = old[:i] + ("\n" if added.startswith("\n") and rest else "") + rest
            edits.write(path, None if was == "created" and not new.strip() else new, old, backup=False)
            rep.row("Your PATH", "removed", "~/.zprofile: the installer's PATH line taken out")
    except edits.Skip as e:
        rep.row("Your PATH", "error", f"~/.zprofile: {e}")
    rec.unlink(missing_ok=True)


def _stale_sockets(rep, wait=5.0):
    """The engine's two sockets, left behind when nothing answers on them any more (the service just stopped may
    still answer for a moment: up to `wait` seconds for that)."""
    end = time.monotonic() + wait
    for sock in (connector_sock(), engine_sock()):
        while sockets._owned(sock) and sockets.alive(sock) and time.monotonic() < end:
            time.sleep(0.25)
        if sockets._owned(sock) and not sockets.alive(sock):
            sock.unlink(missing_ok=True)
            rep.row("Background service", "removed", f"{short(sock)}: removed (nothing answered on it)")


def main(keep_data=False, out=print):
    record = install_record.load()
    brewed = layout.homebrew()
    rep = Report(out)
    out(f"Removing memory from this Mac{'' if record else ' (no install record: looking for what is there)'}.\n")

    ok, note = launchd.remove()
    rep.row("Background service", "removed" if ok else "gone", note)
    _stale_sockets(rep)

    _claude_plugin(record, rep)
    entries = record["files"] if record else apps.discover()
    for entry in entries:
        _file(entry, rep)
    if record:  # files a hand edit or another tool may have added since: look for strays too
        seen = {(e["path"], e["kind"]) for e in entries}
        for entry in apps.discover():
            if (entry["path"], entry["kind"]) not in seen:
                p = apps.unplan(entry)
                if p.state == "remove":
                    _file(entry, rep)

    _zprofile(rep)
    rep.row("API key", *(("removed", "removed from the Keychain") if keychain.delete() else
                          ("gone", "none in the Keychain")))

    data = data_dir()
    # Always asked, --yes or not: the memory cannot be brought back. Nobody at a terminal to answer: it is kept.
    delete = not keep_data and data.exists() and prompt.yes_no(
        f"Delete your memory too? It cannot be brought back. Export first with {COMMAND} export.", False)
    if not data.exists():
        rep.row("Your memory", "gone", f"{short(data)}: already gone")
        connector_sock().unlink(missing_ok=True)
    elif keep_data:
        out(f"{'Your memory':<21}kept in {short(data)}")
    elif delete:
        shutil.rmtree(data, ignore_errors=True)
        rep.row("Your memory", "removed", f"{short(data)} deleted")
        connector_sock().unlink(missing_ok=True)
        for log in logs_dir().glob("memory.log*"):
            log.unlink(missing_ok=True)
        for folder in (home() / "Library/Application Support/LF Labs", logs_dir()):  # when nothing else is in them
            try:
                folder.rmdir()
            except OSError:
                pass
    else:
        out(f"{'Your memory':<21}kept in {short(data)} (delete the folder yourself if you change your mind)")

    uv = uv_bin()
    if brewed:
        pass  # the programs are Homebrew's: said at the end
    elif uv:
        r = run([uv, "tool", "uninstall", CLI_DIST], timeout=120)
        rep.row("Programs", "removed" if r.ok else "gone",
                f"{CLI_DIST} and the engine removed" if r.ok else f"{CLI_DIST} was not installed with uv")
    else:
        rep.row("Programs", "gone", f"uv not found: if ~/.local/share/uv/tools/{CLI_DIST} exists, delete it")

    out("")
    if rep.removed:
        out("Removed: " + ", ".join(dict.fromkeys(rep.removed)) + ".")
    gone = [g for g in dict.fromkeys(rep.gone) if g not in rep.removed]  # removed is the news for that app
    if gone:
        out("Already gone: " + ", ".join(gone) + ".")
    if rep.backups:
        out("Your files from before setup are kept next to them (they could not be put back as they were); delete "
            "them when you like:")
        for b in dict.fromkeys(rep.backups):
            out(f"  {short(b)}")
    local = home() / ".local/bin/uv"
    if brewed:
        out(f"The {COMMAND} command itself came from Homebrew. To remove it:")
        out(f"  brew uninstall {COMMAND}")
    elif os.access(local, os.X_OK):  # where install.sh puts uv (Homebrew's or another uv: not ours to mention)
        u = short(local)  # it stays: other tools may use it. uv's own steps, but never its tool folder (theirs)
        out("uv and the Python it downloaded stay on this Mac (other tools may use them). If nothing else needs them:")
        out(f'  {u} cache clean && rm -rf "$({u} python dir)" {u} {u}x')
    if rep.errors:
        out("Some files were left alone (see above): take the entries out by hand.")
        return 1
    return 0
