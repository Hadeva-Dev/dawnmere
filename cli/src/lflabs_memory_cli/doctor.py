"""doctor: one line per check, then what to do about each warning or failure (spec 9.3)."""
import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
from dataclasses import asdict, dataclass
from importlib import metadata

from . import apps, backend, claude_settings, launchd, layout, models, settings, sockets
from .brand import COMMAND
from .layout import (CONNECTOR, CONNECTOR_VERSION, ENGINE, ENGINE_DIST, OLD_SERVER, SERVER, data_dir, engine_bin, home,
                     short)
from .run import run

SLOW = 1.5
WARMING = 120  # seconds after the service starts in which a slow call is the models still loading
IDLE = 600  # the engine reads a session once it has been quiet this long (EXTRACT_IDLE) or has ended
LICENSES = [("embed", "bge-small-en-v1.5", "MIT"), ("rerank", "ms-marco-MiniLM-L-6-v2", "Apache-2.0"),
            ("sense", "friday-sense-v3 (mmBERT-base fine-tune)", "MIT base, LF Labs weights")]


@dataclass
class Check:
    name: str
    state: str   # ok | warn | fail
    note: str
    fix: str = ""


def version(dist):
    try:
        return metadata.version(dist)
    except metadata.PackageNotFoundError:
        return None


def _db():
    """A read-only connection to the store, or None."""
    p = data_dir() / "memory.db"
    if not p.exists():
        return None
    db = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def _count(db, sql, *args):
    try:
        return db.execute(sql, args).fetchone()[0] or 0
    except sqlite3.Error:
        return None


def _up_seconds(pid):
    """How long the process has run, in seconds (ps etime), or None."""
    r = run(["ps", "-o", "etime=", "-p", str(pid)], timeout=5)
    m = re.fullmatch(r"\s*(?:(\d+)-)?(?:(\d+):)?(\d+):(\d+)\s*", r.out or "")
    if not r.ok or not m:
        return None
    d, h, mi, s = (int(m.group(i) or 0) for i in range(1, 5))
    return ((d * 24 + h) * 60 + mi) * 60 + s


def _uptime(pid):
    up = _up_seconds(pid)
    if up is None:
        return ""
    d, h, mi = up // 86400, up // 3600, up // 60
    return f", up {d} d" if d else f", up {h} h" if h else f", up {mi} min"


def check_engine():
    v = version(ENGINE_DIST) or "?"
    is_loaded, pid = launchd.loaded()
    if pid:
        return Check("engine", "ok", f"{v}, running (pid {pid}){_uptime(pid)}")
    if is_loaded:
        return Check("engine", "fail", f"{v}, loaded but not running",
                     f"see ~/Library/Logs/LF Labs/memory.log, then run {COMMAND} setup again")
    return Check("engine", "fail", f"{v}, not running", f"run {COMMAND} setup")


def check_data(db):
    d = short(data_dir())
    if db is None:
        return Check("data", "fail", f"{d}: no memory yet", f"run {COMMAND} setup")
    mem = _count(db, "select count(*) from memories where status = 'active'") or 0
    claims = _count(db, "select count(*) from claims where status = 'active'")
    size = sum(f.stat().st_size for f in data_dir().glob("memory.db*")) / 1e6
    parts = [f"{mem:,} memor{'y' if mem == 1 else 'ies'}"] + \
        ([f"{claims:,} claim{'' if claims == 1 else 's'}"] if claims is not None else []) + [f"{size:.0f} MB"]
    open_ = [str(p) for p in (data_dir(), layout.lf_labs_dir()) if p.is_dir() and os.stat(p).st_mode & 0o077]
    if open_:
        return Check("data", "warn", f"{d}  ({', '.join(parts)})",
                     "the folder is readable by others: chmod 700 " + " ".join(f"'{p}'" for p in open_))
    return Check("data", "ok", f"{d}  ({', '.join(parts)})")


def check_models():
    man = models.manifest()
    if man is None:
        return Check("models", "warn", "cannot check: the engine has no models list",
                     f"update with {COMMAND} update")
    got = models.check(man)
    bad = [n for n, s in got.items() if s != "ok" and n not in models.OPTIONAL]
    missing_optional = [n for n, s in got.items() if s == "missing" and n in models.OPTIONAL]
    names = ", ".join(n for n, s in got.items() if s == "ok")
    if bad:
        return Check("models", "fail", ", ".join(f"{n} {got[n]}" for n in bad),
                     f"run {COMMAND} setup --models")
    note = f"{names}: checksums match" + (f"; {', '.join(missing_optional)} not installed (word lists decide)"
                                          if missing_optional else "")
    return Check("models", "ok", note)


def check_hook():
    if not (data_dir() / "memory.db").exists():  # running the engine would create its data folder
        return Check("hook speed", "fail", "not set up", f"run {COMMAND} setup")
    eng = engine_bin()
    if not eng:
        return Check("hook speed", "fail", "the engine command is missing", f"reinstall: {COMMAND} update")
    with tempfile.TemporaryDirectory() as cwd:
        payload = json.dumps({"session_id": f"doctor-{os.getpid()}", "hook_event_name": "UserPromptSubmit",
                              "prompt": "doctor: what do you remember about this project?", "cwd": cwd,
                              "transcript_path": os.path.join(cwd, "none.jsonl")})
        run([eng, "hook-prompt"], input=payload, timeout=10)  # warm-up: the first call after a start loads the models
        t0 = time.monotonic()
        r = run([eng, "hook-prompt"], input=payload, timeout=10)
        took = time.monotonic() - t0
    if not r.ok:
        return Check("hook speed", "fail", "the prompt hook failed", "see ~/Library/Logs/LF Labs/memory.log")
    if took > SLOW:
        pid = launchd.loaded()[1]
        up = _up_seconds(pid) if pid else None
        if up is not None and up < WARMING:
            return Check("hook speed", "ok", f"recall in {took:.2f} s: the service started {up} s ago and is still "
                         f"loading its models (limit {SLOW} s once warm)")
        return Check("hook speed", "warn", f"recall in {took:.2f} s (limit {SLOW} s)",
                     "is the background service running? (engine line above)")
    return Check("hook speed", "ok", f"recall in {took:.2f} s (limit {SLOW} s)")


def check_connector():
    got = sockets.ping_connector()
    if got:
        return Check("connector", "ok", f"answering on {short(sockets.connector_sock())}")
    return Check("connector", "fail", "nothing answers on the connector socket",
                 "Codex and Cursor cannot reach memory: is the background service running?")


def check_node(node, on_npm=True):
    version, problem = node
    if problem:
        return Check("Node.js", "warn", problem, apps.NODE_FIX)
    if on_npm is None:  # offline, or no npm: said, never a failure
        return Check("Node.js", "ok", f"{version}; could not check {CONNECTOR}@{CONNECTOR_VERSION} on npm")
    return Check("Node.js", "ok", version)


def _no_tools(check, node, on_npm=True):
    """An app row while Node.js is missing, or the pinned connector is not on npm: its MCP entry (npx) cannot start,
    so the row warns (the fix is the Node.js row's)."""
    if check.note == "not installed":
        return check
    if node[1]:
        return Check(check.name, "warn", f"{check.note}; {check.name} cannot use memory's tools until Node.js 18 or "
                     "later is installed", check.fix)
    if on_npm is False:
        return Check(check.name, "warn", f"{check.note}; {apps.NOT_ON_NPM}", check.fix)
    return check


READING_WAITS = "background reading waits (recall and remember still work)"


def check_model(cfg, ping=True):
    llm = cfg["llm"]
    name = llm["backend"]
    if name == "none":
        return Check("model", "ok", f"none: {backend.NONE_LOSES}")
    model = backend.MODELS.get(llm["main_model"], llm["main_model"])
    if name == "claude-cli":  # the service runs the claude setup found (claude_path), else one on launchd's PATH
        where = llm.get("claude_path")
        if where and not os.access(where, os.X_OK):
            return Check("model", "warn", f"Claude Code is not at {where} any more",
                         f"run {COMMAND} setup again: it finds claude again")
        if not where and not layout.find_claude():
            return Check("model", "warn", "Claude Code is not installed",
                         f"install Claude Code, then run {COMMAND} setup again")
    s = backend.engine_status(ping) or (backend.claude_status(llm["main_model"], ping) if name == "claude-cli" else None)
    host = backend.claude_endpoint() if name == "claude-cli" else None
    if host:  # Claude Code itself uses another provider: memory's own reading needs a Claude login (engine 0.1.7)
        if s is not None and s.ok and s.logged_in:
            return Check("model", "ok", f"Claude Code {s.version}, logged in, {model}; Claude Code itself is set to use "
                                        f"{host}, background reading uses your Claude login")
        return Check("model", "warn", backend.ENDPOINT_NOTE.format(host=host) + " (recall and remember still work)")
    if name == "anthropic-api" and s is None:
        from . import keychain
        if not keychain.present():  # warn, not fail: background reading waits; recall and remember still work
            return Check("model", "warn", f"API key missing from the Keychain; {READING_WAITS}", f"run {COMMAND} setup")
        return Check("model", "ok", f"Anthropic API key, {model}")
    if s is None:
        return Check("model", "warn", f"could not ask the engine about its model; {READING_WAITS}",
                     f"run {COMMAND} setup to choose again")
    if not s.ok:
        return Check("model", "warn", f"{s.note or 'not working'}; {READING_WAITS}",
                     s.note if "run claude" in (s.note or "") else f"run {COMMAND} setup to choose again")
    if name in backend.PLANS:
        return Check("model", "warn" if s.note else "ok", f"{backend.PLANS[name][1]} {s.version}: "
                     f"{backend.PLANS[name][2].split(',')[0]}" + (f" ({s.note})" if s.note else ""))
    if name == "openai-api":
        who = backend.PROVIDERS.get(llm.get("provider"), llm.get("api_base") or "another provider")
        return Check("model", "warn" if s.note else "ok", f"{who}" + (f" ({s.note})" if s.note else ""))
    who = f"Claude Code {s.version}" if name == "claude-cli" else "Anthropic API key"
    login = ", logged in" if s.logged_in else ""
    return Check("model", "warn" if s.note else "ok", f"{who}{login}, {model}" + (f" ({s.note})" if s.note else ""))


def check_budget(db, cfg):
    limit = cfg["llm"]["daily_calls"]
    if db is None:
        return Check("budget", "ok", f"no calls yet (limit {limit} a day)")
    day = time.strftime("%Y-%m-%d")
    today = _count(db, "select sum(calls) from llm_usage where day = ?", day)
    if today is None:
        return Check("budget", "ok", f"no calls recorded yet (limit {limit} a day)")
    week = db.execute("select sum(in_tok), sum(out_tok) from llm_usage where day >= ?",
                      (time.strftime("%Y-%m-%d", time.localtime(time.time() - 6 * 86400)),)).fetchone()
    k = lambda n: f"{(n or 0) / 7 / 1000:.1f}k"  # noqa: E731
    state = "warn" if today >= limit else "ok"
    return Check("budget", state, f"today {today} of {limit} calls; last 7 days {k(week[0])} in / {k(week[1])} out "
                 "tokens a day", "the rest waits for tomorrow; raise daily_calls in config.toml" if state == "warn"
                 else "")


def check_backlog(db):
    if db is None:
        return Check("backlog", "ok", "0 sessions waiting to be read")
    n = 0
    try:
        for s in db.execute("select transcript, done_line, activity, final from sessions"):
            if not (s["final"] or time.time() - s["activity"] >= IDLE):
                continue
            try:
                with open(s["transcript"], "rb") as f:
                    n += sum(1 for _ in f) > s["done_line"]
            except OSError:
                continue
    except sqlite3.Error:
        pass
    state = "warn" if n > 20 else "ok"
    return Check("backlog", state, f"{n} session{'s' if n != 1 else ''} waiting to be read",
                 "the model may be over its budget or logged out (model line)" if state == "warn" else "")


def check_claude():
    if not apps.installed("claude-code"):
        return Check("Claude Code", "ok", "not installed")
    r = run(["claude", "plugin", "list"], timeout=30)
    for pid in (claude_settings.PLUGIN_ID, claude_settings.OLD_PLUGIN_ID):
        if not (r.ok and pid in r.out):
            continue
        name = pid.split("@")[0]
        m = re.search(rf"{re.escape(pid)}\S*\s+(?:Version:\s*)?v?(\d[\w.]*)", r.out)  # 2.1.301 lists "Version: x"
        plugin = f"plugin {name}" + (f" {m.group(1)}" if m else "")
        if pid == claude_settings.OLD_PLUGIN_ID:  # installed before 0.1.10: it works, under its old name
            return Check("Claude Code", "warn", f"{plugin} (its old name)", f"run {COMMAND} setup to rename it")
        if not apps.hook_engine():  # where the plugin's hook launcher looks, never PATH
            return Check("Claude Code", "warn", f"{plugin}, but its hooks cannot find the engine",
                         f"run {COMMAND} setup again")
        return Check("Claude Code", "ok", f"{plugin}, hooks on")
    try:
        text = (home() / ".claude/settings.json").read_text()
    except OSError:
        text = ""
    if "hook-prompt" in text and ENGINE in text:  # setup's fallback: the tools come from `claude mcp add`
        if shutil.which("claude") is None:
            return Check("Claude Code", "warn", "hooks only, no MCP tools (the claude command was not found)",
                         f"install Claude Code's claude command, then run {COMMAND} setup again")
        if not run(["claude", "mcp", "get", SERVER], timeout=30).ok:
            if apps.old_claude_mcp():
                return Check("Claude Code", "warn", f"MCP + hooks in ~/.claude/settings.json, the MCP entry under its "
                             f"old name {OLD_SERVER}", f"run {COMMAND} setup to rename it")
            return Check("Claude Code", "warn", "hooks only, no MCP tools (claude mcp add failed)",
                         f"run {COMMAND} setup again")
        return Check("Claude Code", "ok", "MCP + hooks in ~/.claude/settings.json")
    return Check("Claude Code", "warn", "not connected", f"run {COMMAND} setup")


def _has(path, needle):
    try:
        return needle in path.read_text()
    except OSError:
        return False


def _old_name(app, row):
    """row, or a warning when the app's MCP entry is still under its name from before 0.1.10 (it works; setup and update
    rename it)."""
    plan = apps.plan_rename(app)
    if row.state != "ok" or plan is None or plan.state != "add":
        return row
    return Check(row.name, "warn", f"{row.note}; its entry is under the old name {OLD_SERVER}",
                 f"run {COMMAND} setup to rename it")


def check_codex():
    if not apps.installed("codex"):
        return Check("Codex", "ok", "not installed")
    mcp = _has(home() / ".codex/config.toml", f"{CONNECTOR}@")
    hook = _has(home() / ".codex/hooks.json", "hook-prompt")
    if mcp and hook:
        return _old_name("codex", Check("Codex", "ok", "MCP + hook (Codex asks you to trust the hook once: /hooks)"))
    if mcp:
        return Check("Codex", "warn", "MCP only: no prompt hook", f"run {COMMAND} setup")
    return Check("Codex", "warn", "not connected", f"run {COMMAND} setup")


def check_cursor():
    if not apps.installed("cursor"):
        return Check("Cursor", "ok", "not installed")
    mcp = _has(home() / ".cursor/mcp.json", f"{CONNECTOR}@")
    hook = _has(home() / ".cursor/hooks.json", "hook-cursor-start")
    if mcp:
        from . import access
        level = access.current_level("cursor") or "work only"
        return _old_name("cursor", Check("Cursor", "ok" if hook else "warn", f"MCP, {level} (change it: {COMMAND} "
                                         "access cursor)" + ("" if hook else "; no session-start hook"),
                                         "" if hook else f"run {COMMAND} setup"))
    return Check("Cursor", "warn", "not connected", f"run {COMMAND} setup")


def check_mcp_only():
    """A row for each of Windsurf, Gemini CLI and VS Code that is on this Mac (none when it is not)."""
    rows = []
    for app, (label, _, path, _) in apps.MCP_ONLY.items():
        if not apps.installed(app):
            continue
        if _has(home() / path, f"{CONNECTOR}@"):
            rows.append(_old_name(app, Check(label, "ok", "MCP, work only")))
        else:
            rows.append(Check(label, "warn", "not connected", f"run {COMMAND} setup"))
    return rows


def check_command():
    if layout.on_shell_path():
        return Check(COMMAND, "ok", "on your PATH")
    return Check(COMMAND, "warn", "not on your PATH: a new Terminal window will not find it",
                 f"add this line to ~/.zprofile, then open a new Terminal window: {layout.path_line()}")


def check_held():
    """[a row] when the engine holds app saves back from prompts (`held --count`), else []: they wait for the user's
    confirm code, which `held` shows."""
    eng = engine_bin()
    r = run([eng, "held", "--count"], timeout=15) if eng else None
    n = int(r.out.strip()) if r and r.ok and r.out.strip().isdigit() else 0
    if not n:
        return []
    return [Check("held back", "ok", f"{n} app save{'s' if n != 1 else ''} held back from prompts: {COMMAND} held "
                  "shows them and their confirm codes")]


def check_privacy(cfg):
    """What stays and what goes: the memory is on this Mac; background reading sends conversations to the user's own
    model (their Claude plan or API key)."""
    p, on = cfg["privacy"], lambda x: "on" if x else "off"
    return Check("privacy", "ok", f"memory stored on this Mac; background reading {on(cfg['llm']['backend'] != 'none')}; "
                 f"Codex sessions {on(p['codex_sessions'])}; chat index {on(p['chat_index'])}; no telemetry")


def check_backups():
    snaps = sorted((data_dir() / "backup").glob("memory-*.db"), key=lambda p: p.stat().st_mtime)
    if not snaps:
        return Check("backups", "ok", "no local snapshot yet (the first one is made tonight)")
    age = (time.time() - snaps[-1].stat().st_mtime) / 3600
    when = f"{age:.0f} h ago" if age < 48 else f"{age / 24:.0f} d ago"
    state = "warn" if age > 72 else "ok"
    return Check("backups", state, f"last local snapshot {when} ({len(snaps)} kept)",
                 "is the background service running? (engine line above)" if state == "warn" else "")


def checks(ping=True):
    cfg = settings.load()
    db = _db()
    node = apps.node_status()
    on_npm = apps.connector_on_npm() if not node[1] else True
    try:
        return [check_engine(), check_data(db), check_models(), check_hook(), check_connector(),
                check_node(node, on_npm), check_model(cfg, ping), check_budget(db, cfg), check_backlog(db),
                *(_no_tools(c, node, on_npm) for c in (check_claude(), check_codex(), check_cursor(), *check_mcp_only())),
                check_command(), check_privacy(cfg), check_backups(), *check_held()]
    finally:
        if db is not None:
            db.close()


def report():
    """Counts only: nothing a user would mind pasting into a public issue (no text, names or paths)."""
    cfg = settings.load()
    db = _db()
    lines = [f"cli {version('lflabs-memory-cli') or '?'}, engine {version(ENGINE_DIST) or '?'}, connector "
             f"{CONNECTOR_VERSION}", f"backend {cfg['llm']['backend']}, model {cfg['llm']['main_model']}, "
             f"daily_calls {cfg['llm']['daily_calls']}"]
    if db is not None:
        try:
            for row in db.execute("select kind, count(*) from memories where status = 'active' group by kind"):
                lines.append(f"memories kind={row[0]}: {row[1]}")
            for row in db.execute("select origin, count(*) from memories where status = 'active' group by origin"):
                lines.append(f"memories origin={row[0]}: {row[1]}")
            claims = _count(db, "select count(*) from claims where status = 'active'")
            if claims is not None:
                lines.append(f"claims: {claims}")
            saves = _count(db, "select count(*) from saves where at > ?", time.time() - 7 * 86400)
            if saves is not None:
                lines.append(f"saves last 7 days: {saves}")
        finally:
            db.close()
    for c in checks(ping=False):
        lines.append(f"check {c.name}: {c.state}")
    return "\n".join(lines)


def main(as_json=False, as_report=False, licenses=False, out=print):
    if licenses:
        for name, model, lic in LICENSES:
            out(f"{name:<8}{model:<42}{lic}")
        return 0
    if as_report:
        out(report())
        return 0
    got = checks()
    if as_json:
        out(json.dumps([asdict(c) for c in got], indent=2))
    else:
        for c in got:
            out(f"{c.name:<14}{c.state:<6}{c.note}")
        todo = [c for c in got if c.state != "ok" and c.fix]
        if todo:
            out("")
            for c in todo:
                out(f"{c.name}: {c.fix}")
    return 1 if any(c.state == "fail" for c in got) else 0
