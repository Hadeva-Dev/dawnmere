"""Wiring Claude Code, Codex and Cursor to memory, and taking it out again (spec 9.2 step 7, 9.4).

Each app file gets a plan first: what would change, as exact text, before anything touches the disk. Plans are pure
(they read, never write); setup applies them through edits.write, uninstall builds the reverse plan.

Ours, wherever it appears:
- an MCP entry is ours when it runs the connector package (args hold "lflabs-memory-connector@...");
- a hook is ours when its command runs the engine's console script (lflabs-memory) with one of our subcommands.
An entry named lflabs-memory that is not ours (another tool's) is left alone and reported.
"""
import json
import re
import shlex
from dataclasses import dataclass

from . import edits
from .edits import Skip
from .layout import CLIENT_ENV, CONNECTOR, CONNECTOR_VERSION, ENGINE, SERVER, home

KEY_ENV = "LFLABS_MEMORY_CLIENT_KEY"  # an app trusted with more than work only carries its key (access.py)

LABELS = {"claude-code": "Claude Code", "codex": "Codex", "cursor": "Cursor"}
DEFAULT = ("claude-code", "codex", "cursor")
# Claude Code's hooks (the plugin's hooks/hooks.json, and the fallback in ~/.claude/settings.json)
CLAUDE_HOOKS = (("UserPromptSubmit", "hook-prompt", 10), ("SessionStart", "hook-session-start", 120),
                ("Stop", "hook-activity", 10), ("SessionEnd", "hook-session-end", 10))
HINTS = {"codex": "type /hooks once", "cursor": "restart Cursor"}


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


def connector_args():
    return ["-y", f"{CONNECTOR}@{CONNECTOR_VERSION}"]


def ours_server(v):
    args = v.get("args") if isinstance(v, dict) else None
    return isinstance(args, list) and any(isinstance(a, str) and (a == CONNECTOR or a.startswith(CONNECTOR + "@"))
                                          for a in args)


def ours_command(cmd):
    """A hook command that runs our engine: its program (after any VAR=value words) is lflabs-memory or a path to it."""
    if not isinstance(cmd, str):
        return False
    try:
        words = shlex.split(cmd)
    except ValueError:
        return False
    words = [w for w in words if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", w)]
    return bool(words) and (words[0] == ENGINE or words[0].endswith("/" + ENGINE)) and len(words) > 1 and \
        words[1].startswith("hook-")


def engine_cmd(engine, sub, client=None, key=None):
    return ((f"{CLIENT_ENV}={client} " if client else "") + (f"{KEY_ENV}={shlex.quote(key)} " if key else "")
            + f"{shlex.quote(engine)} {sub}")


# ---------- plans: what setup adds ----------

def _mcp_entry(client, key=None):
    return {"command": "npx", "args": connector_args(), "env": {CLIENT_ENV: client, **({KEY_ENV: key} if key else {})}}


def plan_mcp_json(app, client, path, key="mcpServers", client_key=None):
    """Cursor's mcp.json (and any app with the same shape): our server entry under `key`."""
    try:
        old = edits.read(path)
        data = edits.load_json(old)
        servers = data.get(key, {})
        if not isinstance(servers, dict):
            raise Skip(f'its "{key}" is not an object: left alone; add this by hand')
        if any(ours_server(v) for v in servers.values()):
            return Plan(app, "mcp-json", path, "done", f"already has {SERVER}")
        if SERVER in servers:
            return Plan(app, "mcp-json", path, "stale", f"has another {SERVER} entry: left alone (remove it and rerun)")
        new = json.loads(json.dumps(data))
        new.setdefault(key, {})[SERVER] = _mcp_entry(client, client_key)
        added = json.dumps({SERVER: _mcp_entry(client, client_key)}, indent=2)
        return Plan(app, "mcp-json", path, "add", f'add {key}."{SERVER}"', added, edits.dump_json(new, old or ""), old,
                    added)
    except Skip as e:
        return Plan(app, "mcp-json", path, "error", str(e), json.dumps({SERVER: _mcp_entry(client)}, indent=2))


def codex_block(client="codex"):
    args = ", ".join(json.dumps(a) for a in connector_args())
    return (f"[mcp_servers.{SERVER}]\ncommand = \"npx\"\nargs = [{args}]\n\n"
            f"[mcp_servers.{SERVER}.env]\n{CLIENT_ENV} = {json.dumps(client)}\n")


def plan_codex_toml(path):
    block = codex_block()
    try:
        old = edits.read(path)
        servers = edits.load_toml(old).get("mcp_servers") or {}
        if not isinstance(servers, dict):
            raise Skip("its mcp_servers is not a table: left alone; add these lines by hand")
        if any(ours_server(v) for v in servers.values()):
            return Plan("codex", "codex-toml", path, "done", f"already has {SERVER}")
        if SERVER in servers:
            return Plan("codex", "codex-toml", path, "stale", f"has another [mcp_servers.{SERVER}]: left alone")
        new = edits.append_toml(old, block)
        return Plan("codex", "codex-toml", path, "add", f"add [mcp_servers.{SERVER}]", block, new, old, block)
    except Skip as e:
        return Plan("codex", "codex-toml", path, "error", str(e), block)


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


def plan_cursor_hooks(path, engine, client_key=None):
    entry = {"command": engine_cmd(engine, "hook-cursor-start", "cursor", client_key), "timeout": 10}
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
    raise ValueError(app)


def installed(app, h=None):
    """Whether an app is on this Mac: its folder exists (Claude Code also needs the claude command)."""
    h = h or home()
    return (h / {"claude-code": ".claude", "codex": ".codex", "cursor": ".cursor"}[app]).is_dir()


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


def _drop_toml(text, block):
    """text without our [mcp_servers.lflabs-memory] tables: the exact block setup appended when it is still there,
    else the tables found by their headers. (new text, removed?)"""
    if block:
        e = edits.eol(text)
        for cand in (e + block.replace("\n", e), block.replace("\n", e)):
            if text.count(cand) == 1:
                return text.replace(cand, "", 1), True
    s = re.escape(SERVER)
    head = re.compile(rf'(?m)^[ \t]*\[[ \t]*mcp_servers\.(?:{s}|"{s}")(?:\.env)?[ \t]*\][ \t]*\r?\n?')
    out, removed = text, False
    while (m := head.search(out)):
        nxt = re.compile(r"(?m)^[ \t]*\[").search(out, m.end())
        out = out[:m.start()] + (out[nxt.start():] if nxt else "")
        removed = True
    return out, removed


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
            new, removed = _drop_toml(old, entry.get("added"))
            edits.load_toml(new)
            return Plan(app, kind, path, "remove", f"remove [mcp_servers.{SERVER}]", new=new, old=old)
        data = edits.load_json(old)
        if kind == "mcp-json":
            key = entry.get("key", "mcpServers")
            servers = data.get(key) if isinstance(data.get(key), dict) else {}
            mine = [k for k, v in servers.items() if ours_server(v)]
            if not mine:
                return Plan(app, kind, path, "gone", f"no {SERVER} entry (already removed)")
            new = json.loads(json.dumps(data))
            for k in mine:
                del new[key][k]
            return Plan(app, kind, path, "remove", f'remove {key}."{SERVER}"', new=edits.dump_json(new, old), old=old)
        new, n = _drop_hooks(data)
        if not n:
            return Plan(app, kind, path, "gone", "no memory hooks (already removed)")
        if kind == "cursor-hooks" and entry.get("created") and new in ({"version": 1}, {"version": 1, "hooks": {}}):
            return Plan(app, kind, path, "remove", "remove hooks.json (setup created it)", new=None, old=old)
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
            {"app": "claude-code", "kind": "claude-settings", "path": str(h / ".claude/settings.json")}]


def apply(plan, record):
    """Write one "add" plan and note it in the install record. Raises edits.Skip (the file is then as it was)."""
    from . import install_record
    backup = edits.write(plan.path, plan.new, plan.old)
    install_record.add_file(record, plan, backup, edits.sha256(plan.new))
    return backup
