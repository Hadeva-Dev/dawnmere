"""Wiring Claude Code, Codex and Cursor to memory, and taking it out again (spec 9.2 step 7, 9.4).

Each app file gets a plan first: what would change, as exact text, before anything touches the disk. Plans are pure
(they read, never write); setup applies them through edits.write, uninstall builds the reverse plan.

Ours, wherever it appears:
- an MCP entry is ours when it runs the connector package (args hold layout.CONNECTOR followed by "@<version>");
- a hook is ours when its command runs the engine's console script (lflabs-memory) with one of our subcommands.
An entry named SERVER that is not ours (another tool's) is left alone and reported. Ours under OLD_SERVER (the name
before 0.1.10) is renamed to SERVER, or dropped when SERVER already holds ours: an app never ends up with two.
"""
import json
import os
import re
import shlex
import shutil
from dataclasses import dataclass

from importlib import metadata

from . import edits
from .brand import REPO
from .edits import Skip
from .layout import (CLI_DIST, CLIENT_ENV, CONNECTOR, CONNECTOR_VERSION, ENGINE, MARKETPLACE, OLD_SERVER, SERVER,
                     engine_record, home)
from .run import run

KEY_ENV = "LFLABS_MEMORY_CLIENT_KEY"  # an app trusted with more than work only carries its key (access.py)

# Apps that get the MCP entry and nothing else (no hook: they recall when they call the tool). Each: its label, the
# folder that shows it is installed, its MCP file and the key our entry goes under there. The client names are the
# engine's (connect_apps.APPS). An app named only by its config is held to work notes, like Cursor.
LIB = "Library/Application Support"
MCP_ONLY = {"windsurf": ("Windsurf", ".codeium/windsurf", ".codeium/windsurf/mcp_config.json", "mcpServers"),
            "gemini": ("Gemini CLI", ".gemini", ".gemini/settings.json", "mcpServers"),
            "copilot": ("VS Code", f"{LIB}/Code/User", f"{LIB}/Code/User/mcp.json", "servers"),
            # From each app's own docs (2026-11-10), the same {"mcpServers": {name: {command, args, env}}} shape:
            "qwen-code": ("Qwen Code", ".qwen", ".qwen/settings.json", "mcpServers"),
            "kimi-code": ("Kimi Code", ".kimi-code", ".kimi-code/mcp.json", "mcpServers"),
            "qoder": ("Qoder CLI", ".qoder", ".qoder/settings.json", "mcpServers"),
            "iflow": ("iFlow CLI", ".iflow", ".iflow/settings.json", "mcpServers"),
            "cline": ("Cline CLI", ".cline", ".cline/data/settings/cline_mcp_settings.json", "mcpServers")}
LABELS = {"claude-code": "Claude Code", "codex": "Codex", "cursor": "Cursor",
          **{app: v[0] for app, v in MCP_ONLY.items()}}
DEFAULT = ("claude-code", "codex", "cursor", *MCP_ONLY)
# Claude Code's hooks (the plugin's hooks/hooks.json, and the fallback in ~/.claude/settings.json)
CLAUDE_HOOKS = (("UserPromptSubmit", "hook-prompt", 10), ("SessionStart", "hook-session-start", 120),
                ("Stop", "hook-activity", 10), ("SessionEnd", "hook-session-end", 10))
HINTS = {"codex": "type /hooks once", "cursor": "restart Cursor", "windsurf": "restart Windsurf",
         "gemini": "restart Gemini CLI", "copilot": "restart VS Code", "qwen-code": "restart Qwen Code",
         "kimi-code": "restart Kimi Code", "qoder": "restart Qoder CLI", "iflow": "restart iFlow CLI",
         "cline": "restart Cline"}
MIN_NODE = 18                # the connector's package.json engines
NODE_FIX = "install Node.js 18 or later from nodejs.org"


@dataclass
class Plan:
    app: str
    kind: str            # mcp-json | codex-toml | codex-hooks | cursor-hooks | claude-settings
    path: object
    state: str           # add | done | stale | error | remove | gone
    note: str
    snippet: str = ""    # the lines to add, shown in a dry run and when a file is left alone
    new: str | None = None
    old: str | None = None
    added: str = ""      # exactly what was added (install.json): the TOML block, or the JSON entry
    rename: bool = False # it moves our entry from OLD_SERVER to SERVER (apply renames install.json's "added" too)


def node_status():
    """(node's version or None, the problem or None). Every app's MCP entry starts the connector with npx."""
    if not shutil.which("npx"):
        return None, "Node.js is not installed"
    r = run(["node", "--version"], timeout=10)
    v = r.out.strip() if r.ok else ""
    m = re.match(r"v?(\d+)\.", v)
    if not m:
        return None, "Node.js is not installed"
    if int(m.group(1)) < MIN_NODE:
        return v, f"Node.js {v} is too old"
    return v, None


def marketplace_source(version=None):
    """What `claude plugin marketplace add` gets: this repo at the release tag the CLI's wheels come from, so the
    plugin (and what its hooks run) changes with a release, never with a push to main. LFLABS_MEMORY_MARKETPLACE
    overrides it (a local checkout, for testing)."""
    return os.environ.get("LFLABS_MEMORY_MARKETPLACE") or f"{REPO}#v{version or metadata.version(CLI_DIST)}"


def marketplace_pinned(version=None):
    """Whether Claude Code's marketplace (`claude plugin marketplace list --json`) is this repo at this release's tag.
    True when it cannot tell (an old claude), or under LFLABS_MEMORY_MARKETPLACE (a local checkout)."""
    if os.environ.get("LFLABS_MEMORY_MARKETPLACE"):
        return True
    r = run(["claude", "plugin", "marketplace", "list", "--json"], timeout=30)
    try:
        listed = json.loads(r.out) if r.ok else None
    except ValueError:
        listed = None
    if not isinstance(listed, list):
        return True
    ours = next((m for m in listed if isinstance(m, dict) and m.get("name") == MARKETPLACE), None)
    return ours is not None and ours.get("repo") == REPO and \
        ours.get("ref") == f"v{version or metadata.version(CLI_DIST)}"


def hook_engine():
    """The engine the Claude Code plugin's hooks run, found where plugin/scripts/engine looks (never PATH): the path
    setup recorded, else uv's tool bin folder. None when there is none."""
    try:
        recorded = engine_record().read_text().strip()
    except OSError:
        recorded = ""
    bins = [os.environ.get("UV_TOOL_BIN_DIR"), os.environ.get("XDG_BIN_HOME"), str(home() / ".local/bin")]
    for e in [recorded] + [os.path.join(b, ENGINE) for b in bins if b]:
        if os.path.isabs(e) and os.access(e, os.X_OK):
            return e
    return None


def old_claude_mcp():
    """Whether Claude Code has setup's fallback MCP entry under OLD_SERVER (`claude mcp get` shows our connector)."""
    r = run(["claude", "mcp", "get", OLD_SERVER], timeout=30)
    return r.ok and CONNECTOR in r.out


def connector_on_npm():
    """Whether the connector version every app's entry pins (npx CONNECTOR@X) is on npm: True, False, or None
    when it cannot be told (no npm, offline). A yes is remembered in the data folder; a no or a don't-know is asked
    again next time."""
    from .layout import data_dir
    mark = data_dir() / "connector-on-npm"
    try:
        if mark.read_text().strip() == CONNECTOR_VERSION:
            return True
    except OSError:
        pass
    if not shutil.which("npm"):
        return None
    r = run(["npm", "view", f"{CONNECTOR}@{CONNECTOR_VERSION}", "version"], timeout=20)
    if r.ok and r.out.strip() == CONNECTOR_VERSION:
        if data_dir().is_dir():
            mark.write_text(CONNECTOR_VERSION + "\n")
        return True
    if "E404" in r.err + r.out or (r.ok and not r.out.strip()):
        return False
    return None


NOT_ON_NPM = f"the connector {CONNECTOR}@{CONNECTOR_VERSION} is not on npm yet: apps cannot start memory's tools"


def connector_args():
    return ["-y", f"{CONNECTOR}@{CONNECTOR_VERSION}"]


def _is_engine(word):
    return isinstance(word, str) and (word == ENGINE or word.endswith("/" + ENGINE))


def _program(words):
    """The words from the program on: without `env` and VAR=value words (whatever the names: older engines wrote
    JARVIS_MEMORY_*), and without a python that runs the engine's script (the engine's own `connect` writes
    "/…/python /…/lflabs-memory hook-prompt")."""
    words = [w for w in words if w != "env" and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", w)]
    if len(words) > 1 and re.fullmatch(r"python[0-9.]*", words[0].rsplit("/", 1)[-1]) and _is_engine(words[1]):
        words = words[1:]
    return words


def ours_server(v):
    """An MCP entry that runs the connector package, or the engine itself (`lflabs-memory serve`, as the engine's own
    `connect` writes it), whatever its env holds."""
    args = v.get("args") if isinstance(v, dict) else None
    if not isinstance(args, list):
        return False
    if any(isinstance(a, str) and (a == CONNECTOR or a.startswith(CONNECTOR + "@")) for a in args):
        return True
    words = _program([v.get("command")] + args) if all(isinstance(a, str) for a in args) and \
        isinstance(v.get("command"), str) else []
    return len(words) > 1 and _is_engine(words[0]) and words[1] == "serve"


def ours_command(cmd):
    """A hook command that runs our engine: its program (after any env and VAR=value words, and a python running it)
    is lflabs-memory or a path to it, with one of our hook- subcommands."""
    if not isinstance(cmd, str):
        return False
    try:
        words = _program(shlex.split(cmd))
    except ValueError:
        return False
    return len(words) > 1 and _is_engine(words[0]) and words[1].startswith("hook-")


def engine_cmd(engine, sub, client=None):
    """A hook's command. Never a key: a shell's command line shows in `ps`."""
    return (f"{CLIENT_ENV}={client} " if client else "") + f"{shlex.quote(engine)} {sub}"


# ---------- plans: what setup adds ----------

def _mcp_entry(client, key=None, under="mcpServers"):
    entry = {"command": "npx", "args": connector_args(),
             "env": {CLIENT_ENV: client, **({KEY_ENV: key} if key else {})}}
    return {"type": "stdio", **entry} if under == "servers" else entry  # VS Code's mcp.json names the transport


def plan_mcp_json(app, client, path, key="mcpServers", client_key=None):
    """Cursor's mcp.json (and any app with the same shape): our server entry under `key`."""
    try:
        old = edits.read(path)
        data = edits.load_json(old)
        servers = data.get(key, {})
        if not isinstance(servers, dict):
            raise Skip(f'its "{key}" is not an object: left alone; add this by hand')
        moved = rename_json(app, path, key, old, data)
        if moved:
            return moved
        if any(ours_server(v) for v in servers.values()):
            return Plan(app, "mcp-json", path, "done", f"already has {SERVER}")
        if SERVER in servers:
            return Plan(app, "mcp-json", path, "stale", f"has another {SERVER} entry: left alone (remove it and rerun)")
        new = json.loads(json.dumps(data))
        new.setdefault(key, {})[SERVER] = _mcp_entry(client, client_key, key)
        added = json.dumps({SERVER: _mcp_entry(client, client_key, key)}, indent=2)
        return Plan(app, "mcp-json", path, "add", f'add {key}."{SERVER}"', added, edits.dump_json(new, old or ""), old,
                    added)
    except Skip as e:
        return Plan(app, "mcp-json", path, "error", str(e), json.dumps({SERVER: _mcp_entry(client, under=key)}, indent=2))


def rename_json(app, path, key, old, data):
    """The plan that moves our entry from OLD_SERVER to SERVER in place (its env, a key too, kept), or drops it when
    SERVER already holds ours; None when there is no old entry of ours."""
    servers = data.get(key) if isinstance(data.get(key), dict) else {}
    if not ours_server(servers.get(OLD_SERVER)):
        return None
    new = json.loads(json.dumps(data))
    if ours_server(servers.get(SERVER)):
        del new[key][OLD_SERVER]
        note = f'remove the old {key}."{OLD_SERVER}" ({SERVER} is there)'
    elif SERVER in servers:
        return Plan(app, "mcp-json", path, "stale", f"has another {SERVER} entry: its old {OLD_SERVER} entry is left "
                    "alone (remove one and rerun)")
    else:
        new[key] = {(SERVER if k == OLD_SERVER else k): v for k, v in new[key].items()}
        note = f'rename {key}."{OLD_SERVER}" to "{SERVER}"'
    return Plan(app, "mcp-json", path, "add", note, "", edits.dump_json(new, old), old, rename=True)


def plan_rename(app, h=None):
    """The rename plans for one app's MCP file (update runs these alone: it never adds an entry)."""
    h = h or home()
    path, key = {"codex": (h / ".codex/config.toml", None), "cursor": (h / ".cursor/mcp.json", "mcpServers"),
                 **{a: (h / v[2], v[3]) for a, v in MCP_ONLY.items()}}[app]
    try:
        old = edits.read(path)
        if old is None:
            return None
        if key is None:
            return rename_toml(path, old, edits.load_toml(old).get("mcp_servers") or {})
        data = edits.load_json(old)
        return rename_json(app, path, key, old, data) if isinstance(data, dict) else None
    except Skip:
        return None


def codex_block(client="codex", key=None):
    args = ", ".join(json.dumps(a) for a in connector_args())
    return (f"[mcp_servers.{SERVER}]\ncommand = \"npx\"\nargs = [{args}]\n\n"
            f"[mcp_servers.{SERVER}.env]\n{CLIENT_ENV} = {json.dumps(client)}\n"
            + (f"{KEY_ENV} = {json.dumps(key)}\n" if key else ""))


def plan_codex_toml(path, client_key=None):
    block = codex_block(key=client_key)
    try:
        old = edits.read(path)
        servers = edits.load_toml(old).get("mcp_servers") or {}
        if not isinstance(servers, dict):
            raise Skip("its mcp_servers is not a table: left alone; add these lines by hand")
        moved = rename_toml(path, old, servers)
        if moved:
            return moved
        if any(ours_server(v) for v in servers.values()):
            return Plan("codex", "codex-toml", path, "done", f"already has {SERVER}")
        if SERVER in servers:
            return Plan("codex", "codex-toml", path, "stale", f"has another [mcp_servers.{SERVER}]: left alone")
        new = edits.append_toml(old, block)
        return Plan("codex", "codex-toml", path, "add", f"add [mcp_servers.{SERVER}]", block, new, old, block)
    except Skip as e:
        return Plan("codex", "codex-toml", path, "error", str(e), codex_block())


def _toml_heads(name):
    """[mcp_servers.NAME] and [mcp_servers.NAME.env] (and any other sub-table) headers, the name bare or quoted."""
    s = re.escape(name)
    return re.compile(rf'(?m)^([ \t]*\[[ \t]*mcp_servers\.)(?:{s}|"{s}")((?:\.[^\]\r\n]*)?[ \t]*\])')


def rename_toml(path, old, servers):
    """Codex's config.toml with our [mcp_servers.OLD_SERVER] tables (the .env one, with any key, too) renamed to
    SERVER, or taken out when SERVER already holds ours; None when there is no old table of ours."""
    if not isinstance(servers, dict) or not ours_server(servers.get(OLD_SERVER)):
        return None
    if ours_server(servers.get(SERVER)):
        new, note = _drop_toml(old, None, (OLD_SERVER,))[0], f"remove the old [mcp_servers.{OLD_SERVER}] ({SERVER} is there)"
    elif SERVER in servers:
        return Plan("codex", "codex-toml", path, "stale", f"has another [mcp_servers.{SERVER}]: its old "
                    f"[mcp_servers.{OLD_SERVER}] is left alone (remove one and rerun)")
    else:
        new, note = _toml_heads(OLD_SERVER).sub(rf"\g<1>{SERVER}\g<2>", old), \
            f"rename [mcp_servers.{OLD_SERVER}] to [mcp_servers.{SERVER}]"
    try:
        after = edits.load_toml(new).get("mcp_servers") or {}
    except Skip:
        after = {}
    if OLD_SERVER in after or not ours_server(after.get(SERVER)) or \
            (servers[OLD_SERVER].get("env") != after[SERVER].get("env") and not ours_server(servers.get(SERVER))):
        return Plan("codex", "codex-toml", path, "error", f"its [mcp_servers.{OLD_SERVER}] is not in plain tables: left "
                    f"alone; rename it to {SERVER} by hand")
    return Plan("codex", "codex-toml", path, "add", note, "", new, old, rename=True)


def renamed_added(added):
    """install.json's record of what setup added, with our entry's old name changed to SERVER (uninstall looks for
    exactly that text)."""
    return _toml_heads(OLD_SERVER).sub(rf"\g<1>{SERVER}\g<2>", added or "").replace(
        json.dumps(OLD_SERVER) + ":", json.dumps(SERVER) + ":")


def _hooks_add(app, kind, path, data, old, adds, note):
    """Add hooks to data["hooks"][event] for each (event, entry, group): group wraps the entry in {"hooks": [...]}
    (Claude Code, Codex); Cursor lists entries directly. Events that already run our command are skipped."""
    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        raise Skip("has hooks in a shape I don't know: left alone; add the hook by hand")
    new = json.loads(json.dumps(data))
    new_hooks = new.setdefault("hooks", {})
    added = {}
    for event, entry, group in adds:
        items = hooks.get(event, [])
        if not isinstance(items, list):
            raise Skip(f"its {event} hooks are not a list: left alone; add the hook by hand")
        flat = [h for g in items if isinstance(g, dict) for h in (g.get("hooks") or [] if group else [g])]
        if any(isinstance(h, dict) and ours_command(h.get("command")) and entry["command"].split()[-1] in h["command"]
               for h in flat):
            continue
        new_hooks.setdefault(event, []).append({"hooks": [entry]} if group else entry)
        added[event] = entry
    if not added:
        return Plan(app, kind, path, "done", "already has the hook" + ("s" if len(adds) > 1 else ""))
    text = json.dumps(added, indent=2)
    return Plan(app, kind, path, "add", note, text, edits.dump_json(new, old or ""), old, text)


def plan_codex_hooks(path, engine):
    entry = {"type": "command", "command": engine_cmd(engine, "hook-prompt", "codex"), "timeout": 10}
    try:
        old = edits.read(path)
        return _hooks_add("codex", "codex-hooks", path, edits.load_json(old), old,
                          [("UserPromptSubmit", entry, True)], "add a UserPromptSubmit hook")
    except Skip as e:
        return Plan("codex", "codex-hooks", path, "error", str(e), json.dumps(entry, indent=2))


def plan_cursor_hooks(path, engine):
    entry = {"command": engine_cmd(engine, "hook-cursor-start", "cursor"), "timeout": 10}
    try:
        old = edits.read(path)
        data = edits.load_json(old)
        data = {"version": 1, **data} if "version" not in data else data
        return _hooks_add("cursor", "cursor-hooks", path, data, old, [("sessionStart", entry, False)],
                          "add a sessionStart hook")
    except Skip as e:
        return Plan("cursor", "cursor-hooks", path, "error", str(e), json.dumps(entry, indent=2))


def plan_claude_settings(path, engine):
    """The fallback when the plugin cannot be installed: the plugin's four hooks in ~/.claude/settings.json."""
    adds = [(event, {"type": "command", "command": engine_cmd(engine, sub), "timeout": t}, True)
            for event, sub, t in CLAUDE_HOOKS]
    try:
        old = edits.read(path)
        return _hooks_add("claude-code", "claude-settings", path, edits.load_json(old), old, adds,
                          "add the memory hooks")
    except Skip as e:
        return Plan("claude-code", "claude-settings", path, "error", str(e),
                    json.dumps({e: [{"hooks": [h]}] for e, h, _ in adds}, indent=2))


def file_plans(app, engine, h=None):
    """The file plans for one app (Claude Code's plugin is commands, not files: setup.py runs those)."""
    h = h or home()
    if app == "codex":
        return [plan_codex_toml(h / ".codex/config.toml"), plan_codex_hooks(h / ".codex/hooks.json", engine)]
    if app == "cursor":
        return [plan_mcp_json("cursor", "cursor", h / ".cursor/mcp.json"),
                plan_cursor_hooks(h / ".cursor/hooks.json", engine)]
    if app == "claude-code":
        return [plan_claude_settings(h / ".claude/settings.json", engine)]
    if app in MCP_ONLY:
        _, _, path, key = MCP_ONLY[app]
        return [plan_mcp_json(app, app, h / path, key)]
    raise ValueError(app)


def installed(app, h=None):
    """Whether an app is on this Mac: its folder exists (Claude Code also needs the claude command)."""
    h = h or home()
    folders = {"claude-code": ".claude", "codex": ".codex", "cursor": ".cursor", **{a: v[1] for a, v in MCP_ONLY.items()}}
    return (h / folders[app]).is_dir()


# ---------- reverse plans: what uninstall takes out ----------

def _drop_hooks(data):
    """data without our hooks; empty groups, events and an emptied hooks table go too. (new data, how many removed)"""
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return data, 0
    new, n = json.loads(json.dumps(data)), 0
    for event, items in list(hooks.items()):
        if not isinstance(items, list):
            continue
        kept = []
        for g in items:
            if isinstance(g, dict) and isinstance(g.get("hooks"), list):
                inner = [h for h in g["hooks"] if not (isinstance(h, dict) and ours_command(h.get("command")))]
                n += len(g["hooks"]) - len(inner)
                if inner:
                    kept.append({**g, "hooks": inner})
            elif isinstance(g, dict) and ours_command(g.get("command")):
                n += 1
            else:
                kept.append(g)
        if kept:
            new["hooks"][event] = kept
        else:
            del new["hooks"][event]
    if not new["hooks"] and n:
        del new["hooks"]
    return new, n


def _drop_toml(text, block, names=(SERVER, OLD_SERVER)):
    """text without our tables (each of names: [mcp_servers.NAME] and its .env): the exact block setup appended when
    it is still there, else the tables found by their headers. (new text, removed?)"""
    out, removed = text, False
    if block:
        e = edits.eol(text)
        for cand in (e + block.replace("\n", e), block.replace("\n", e)):
            if out.count(cand) == 1:
                out, removed = out.replace(cand, "", 1), True
                break
    for name in names:
        s = re.escape(name)
        head = re.compile(rf'(?m)^[ \t]*\[[ \t]*mcp_servers\.(?:{s}|"{s}")(?:\.env)?[ \t]*\][ \t]*\r?\n?')
        while (m := head.search(out)):
            nxt = re.compile(r"(?m)^[ \t]*\[").search(out, m.end())
            out = out[:m.start()] + (out[nxt.start():] if nxt else "")
            removed = True
    return out, removed


def empty_structure(data, ignore=("version",)):
    """Nothing but empty tables and lists left (a hooks file's "version" aside): what is left of a file setup created
    once our entries are out of it."""
    if isinstance(data, dict):
        return all(k in ignore or empty_structure(v, ()) for k, v in data.items())
    return isinstance(data, list) and all(empty_structure(v, ()) for v in data)


def unplan(entry, h=None):
    """The plan that takes our entry out of one file (entry: an install.json file record, or one found by discovery:
    {"path", "kind", "added", "created"})."""
    from pathlib import Path
    path, kind = Path(entry["path"]), entry["kind"]
    app = entry.get("app", "")
    try:
        old = edits.read(path)
        if old is None:
            return Plan(app, kind, path, "gone", "already gone")
        if kind == "codex-toml":
            servers = edits.load_toml(old).get("mcp_servers") or {}
            if not any(ours_server(v) for v in servers.values()):
                return Plan(app, kind, path, "gone", f"no {SERVER} table (already removed)")
            new, removed = _drop_toml(old, entry.get("added"), [n for n in (SERVER, OLD_SERVER)
                                                                if ours_server(servers.get(n))])
            if entry.get("created") and empty_structure(edits.load_toml(new)) and not new.strip(" \t\r\n#"):
                return Plan(app, kind, path, "remove", "remove config.toml (setup created it)", new=None, old=old)
            edits.load_toml(new)
            return Plan(app, kind, path, "remove", f"remove [mcp_servers.{SERVER}]", new=new, old=old)
        data = edits.load_json(old)
        if kind == "mcp-json":
            key = entry.get("key") or (MCP_ONLY[app][3] if app in MCP_ONLY else "mcpServers")
            servers = data.get(key) if isinstance(data.get(key), dict) else {}
            mine = [k for k, v in servers.items() if ours_server(v)]
            if not mine:
                return Plan(app, kind, path, "gone", f"no {SERVER} entry (already removed)")
            new = json.loads(json.dumps(data))
            for k in mine:
                del new[key][k]
            if entry.get("created") and empty_structure(new):
                return Plan(app, kind, path, "remove", f"remove {path.name} (setup created it)", new=None, old=old)
            return Plan(app, kind, path, "remove", f'remove {key}."{SERVER}"', new=edits.dump_json(new, old), old=old)
        new, n = _drop_hooks(data)
        if not n:
            return Plan(app, kind, path, "gone", "no memory hooks (already removed)")
        if entry.get("created") and empty_structure(new):
            return Plan(app, kind, path, "remove", f"remove {path.name} (setup created it)", new=None, old=old)
        return Plan(app, kind, path, "remove", f"remove {n} memory hook" + ("s" if n > 1 else ""),
                    new=edits.dump_json(new, old), old=old)
    except Skip as e:
        return Plan(app, kind, path, "error", str(e))


def discover(h=None):
    """Our entries found by looking (uninstall without install.json): every file setup may have changed."""
    h = h or home()
    return [{"app": "codex", "kind": "codex-toml", "path": str(h / ".codex/config.toml")},
            {"app": "codex", "kind": "codex-hooks", "path": str(h / ".codex/hooks.json")},
            {"app": "cursor", "kind": "mcp-json", "path": str(h / ".cursor/mcp.json")},
            {"app": "cursor", "kind": "cursor-hooks", "path": str(h / ".cursor/hooks.json")},
            {"app": "claude-code", "kind": "claude-settings", "path": str(h / ".claude/settings.json")},
            *({"app": a, "kind": "mcp-json", "path": str(h / v[2])} for a, v in MCP_ONLY.items())]


def apply(plan, record):
    """Write one "add" plan and note it in the install record. Raises edits.Skip (the file is then as it was).
    Only the first change to a file is backed up (the user's original: the one uninstall puts back), and never a
    file that already holds a key."""
    from . import install_record
    prev = install_record.file_entry(record, plan)
    first = prev is None
    if plan.rename:
        plan.added = renamed_added(prev.get("added")) if prev else ""
    backup = edits.write(plan.path, plan.new, plan.old, secret=KEY_ENV in (plan.new or ""),
                         backup=first and KEY_ENV not in (plan.old or ""))
    install_record.add_file(record, plan, backup, edits.sha256(plan.new))
    return backup
