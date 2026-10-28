"""uninstall: take out everything setup added (spec 9.4). Each step is fine with its thing already gone."""
import shutil
from pathlib import Path

from . import apps, edits, install_record, keychain, launchd, prompt
from .brand import COMMAND
from .layout import CLI_DIST, MARKETPLACE, SERVER, connector_sock, data_dir, logs_dir, short
from .run import run


class Report:
    def __init__(self, out):
        self.out, self.removed, self.gone, self.errors, self.backups = out, [], [], [], []

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


def _file(entry, rep):
    """One app file: put back from its backup while it still holds exactly what setup wrote, else take our entries
    out of it as it is now."""
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
                return rep.row(label, "removed", f"{short(path)}: removed (setup created it)")
            if entry.get("backup") and edits.restore(path, entry["backup"], entry["sha256"]):
                rep.backups.append(entry["backup"])
                return rep.row(label, "removed", f"{short(path)}: put back as it was")
    p = apps.unplan(entry)
    if p.state == "gone":
        return rep.row(label, "gone", f"{short(path)}: {p.note}")
    if p.state == "error":
        return rep.row(label, "error", f"{short(path)}: {p.note}; remove the {SERVER} entries by hand")
    try:
        backup = edits.write(path, p.new, p.old)
    except edits.Skip as e:
        return rep.row(label, "error", f"{short(path)}: {e}")
    if backup:
        rep.backups.append(str(backup))
    rep.row(label, "removed", f"{short(path)}: {p.note}")


def main(keep_data=False, out=print):
    record = install_record.load()
    rep = Report(out)
    out(f"Removing memory from this Mac{'' if record else ' (no install record: looking for what is there)'}.\n")

    ok, note = launchd.remove()
    rep.row("Background service", "removed" if ok else "gone", note)

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
    else:
        out(f"{'Your memory':<21}kept in {short(data)} (delete the folder yourself if you change your mind)")

    if shutil.which("uv"):
        r = run(["uv", "tool", "uninstall", CLI_DIST], timeout=120)
        rep.row("Programs", "removed" if r.ok else "gone",
                f"{CLI_DIST} and the engine removed" if r.ok else f"{CLI_DIST} was not installed with uv")
    else:
        rep.row("Programs", "gone", f"uv not found: if ~/.local/share/uv/tools/{CLI_DIST} exists, delete it")

    out("")
    if rep.removed:
        out("Removed: " + ", ".join(dict.fromkeys(rep.removed)) + ".")
    if rep.gone:
        out("Already gone: " + ", ".join(dict.fromkeys(rep.gone)) + ".")
    if rep.backups:
        out("Backups of your app settings are next to each file; delete them when you like:")
        for b in dict.fromkeys(rep.backups):
            out(f"  {short(b)}")
    if rep.errors:
        out("Some files were left alone (see above): take the entries out by hand.")
        return 1
    return 0
