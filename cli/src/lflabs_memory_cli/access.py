"""What an AI app may see (setup's Cursor question, and `access APP LEVEL` to change it any time).

An app named only by its config is held to work only. Seeing more needs proof: a key the engine registers (only its
hash is kept) and that the app's own entries carry (LFLABS_MEMORY_CLIENT_KEY). The key is made here, handed to the
engine on stdin and written into the app's config; it is never printed, logged or put on a command line.
"""
import json
import os
import secrets
import subprocess
import sys

from . import apps, edits, install_record
from .brand import COMMAND
from .layout import CLIENT_ENV, data_dir, home, short
from .run import run

KEY_ENV = apps.KEY_ENV
LEVELS = ("everything", "nothing-personal", "work", "nothing")
SAYS = {"everything": "everything, personal notes too", "nothing-personal": "everything but personal notes",
        "work": "work notes only", "nothing": "nothing"}
WIDER = ("everything", "nothing-personal")  # beyond work only: needs the key
RANK = {"nothing": 0, "work": 1, "work only": 1, "nothing-personal": 2, "nothing personal": 2, "everything": 3}
# Set in the shells AI apps run their commands in (checked 2026-11): the engine's own list (mem.AGENT_ENV) and three
# more seen here. Claude Code: in its Bash tool's shell (2.1.301). Codex: names its 0.160.0 binary sets for its shell
# tool and sandbox. Cursor: its agent terminal sets CURSOR_AGENT=1 and CURSOR_CONVERSATION_ID, its sandbox
# CURSOR_SANDBOX (cursor-agent-exec in Cursor.app); CURSOR_TRACE_ID is the engine's (every Cursor terminal has it).
# Setup never offers a widening there; the engine's gate is what refuses one.
AGENT_ENV = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "AI_AGENT",
             "CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED", "CODEX_THREAD_ID", "CODEX_SESSION_ID", "CODEX_CI",
             "CURSOR_AGENT", "CURSOR_CONVERSATION_ID", "CURSOR_SANDBOX", "CURSOR_TRACE_ID")


def _engine(code, stdin=""):
    """Run a few lines of the engine in this tool's Python (the CLI and the engine share one environment)."""
    return subprocess.run([sys.executable, "-c", code], input=stdin, capture_output=True, text=True, timeout=60)


def register_key(client):
    """A new key for this client, registered with the engine (only its hash is stored there). None on failure."""
    key = secrets.token_urlsafe(24)
    r = _engine("import sys\nfrom lflabs_memory import mem\n"
                f"mem.clients_add({client!r}, with_key=True, key=sys.stdin.read().strip())", key)
    return key if r.returncode == 0 else None


def set_level(engine, client, level):
    return run([engine, "clients", "level", client, level], timeout=60).ok


def current_level(client):
    """The engine's word for what this client sees ("everything", "work only", ...), or None."""
    if not (data_dir() / "config.toml").exists():
        return None
    r = _engine("from lflabs_memory import access, mem\n"
                f"print(access.level_name(mem.client_hide({client!r}, True), mem) or 'custom')")
    return (r.stdout.strip() or None) if r.returncode == 0 else None


NAMES = {**apps.LABELS, "claude-desktop": "Claude Desktop", "windsurf": "Windsurf", "gemini": "Gemini CLI",
         "copilot": "VS Code (Copilot)"}  # the engine's connect_apps names those it connects itself


def keyless(client):
    """Whether the client's level is wider than work only but it has no key yet, so it still gets work only (an app
    named only by its config proves nothing: connect_apps.needs_key). False when the engine cannot say."""
    if not (data_dir() / "config.toml").exists():
        return False
    r = _engine("from lflabs_memory import connect_apps, mem\n"
                f"key = (mem.client_policies().get({client!r}) or {{}}).get('key_sha256')\n"
                f"print(int(connect_apps.needs_key(mem, {client!r}) and not key))")
    return r.returncode == 0 and r.stdout.strip() == "1"


# ---------- Cursor's two files with a key ----------

def cursor_plans(engine, key, h=None):
    """Cursor's mcp.json entry with the key (added, or the key put in place), and its start hook as setup writes it.
    The key is never put on the hook's command line (a shell's argv shows in `ps`): the start block is then held to
    work only, while the recall tool, which carries the key, sees what Cursor may see."""
    h = h or home()
    return [plan_key_json(h / ".cursor/mcp.json", key), apps.plan_cursor_hooks(h / ".cursor/hooks.json", engine)]


def mask(text, key):
    return text.replace(key, "<the key setup made>") if key and text else text


def plan_key_json(path, key):
    p = apps.plan_mcp_json("cursor", "cursor", path, client_key=key)
    if p.state != "done":
        return p
    try:  # our entry is there already: give it the key
        old = edits.read(path)
        data = edits.load_json(old)
        new = json.loads(json.dumps(data))
        entry = next(v for v in new["mcpServers"].values() if apps.ours_server(v))
        env = entry.get("env") if isinstance(entry.get("env"), dict) else {}
        if env.get(KEY_ENV) == key:
            return p
        entry["env"] = {**env, CLIENT_ENV: "cursor", KEY_ENV: key}
        return apps.Plan("cursor", "mcp-json", path, "add", "give its entry a key", "", edits.dump_json(new, old), old,
                         "")
    except edits.Skip as e:
        return apps.Plan("cursor", "mcp-json", path, "error", str(e))


def agent_shell(env=None):
    """The first AI-app marker set in this environment, or None."""
    env = os.environ if env is None else env
    return next((k for k in AGENT_ENV if env.get(k)), None)


# Processes an AI app runs commands under, and how they are looked up: the engine's own list (access.AGENT_PROCS),
# /bin/ps by its absolute path with a fixed PATH, so nothing an agent put on PATH answers instead.
AGENT_PROCS = ("claude", "codex", "cursor", "cursor helper", "node", "windsurf", "copilot", "aider", "goose")
PS, SAFE_ENV = "/bin/ps", {"PATH": "/usr/bin:/bin"}


def agent_ancestor(pid=None, run=None):
    """The name of an AI app among this process's ancestors, up to launchd; "unknown (...)" when the walk cannot be
    read (fails closed); None when there is none (which proves nothing about a person on its own)."""
    run = run or subprocess.run
    pid, seen = pid or os.getppid(), set()
    while pid != 1:
        if pid in seen or pid <= 0:
            return "unknown (a broken process chain)"
        seen.add(pid)
        try:
            out = run([PS, "-o", "ppid=,comm=", "-p", str(pid)], capture_output=True, text=True, timeout=5,
                      env=SAFE_ENV).stdout
        except (OSError, subprocess.SubprocessError):
            return "unknown (ps failed)"
        parts = (out or "").strip().split(None, 1)
        if len(parts) < 2 or not parts[0].isdigit():
            return "unknown (ps gave nothing readable)"
        name = os.path.basename(parts[1]).lower()
        if any(name == a or name.startswith(a + " ") or name.startswith(a + ".") for a in AGENT_PROCS):
            return name
        pid = int(parts[0])
    return None


def engine_widens(engine, app, level):
    """The engine's own `clients level`, on this terminal: its gate refuses an AI app's shell or a process an AI app
    started, asks for the app's name, then needs Allow clicked in a macOS dialog, and logs the change to the access
    history. It says refusals itself, exit 0 or not, so whether the level took is read back. True when it did."""
    subprocess.run([engine, "clients", "level", app, level], timeout=600)  # stdin, stdout, stderr: this terminal
    return RANK.get(current_level(app) or "", -1) >= RANK[level]


def widens(app, level):
    """Whether level lets the app see more than it does now (an unknown or custom level counts as work only)."""
    now = current_level(app) or "work"
    return RANK[level] > RANK.get(now, 1)


def widen_cursor(engine, record=None, say=print):
    """Register a new key for Cursor and put it in both its files. True when Cursor will be recognised by it."""
    key = register_key("cursor")
    if not key:
        say("The memory service could not register Cursor's key; Cursor stays at work only.")
        return False
    ok = True
    for p in cursor_plans(engine, key):
        if p.state == "add":
            try:
                p.added, p.snippet = mask(p.added, key), mask(p.snippet, key)
                apps.apply(p, record if record is not None else install_record.empty())
            except edits.Skip as e:
                say(f"{short(p.path)}: {e}")
                ok = False
        elif p.state in ("error", "stale"):
            say(f"{short(p.path)}: {p.note}")
            ok = False
    return ok


# ---------- access APP LEVEL ----------

def main(app, level, engine, say=print):
    app = app.lower()
    if level is not None and level not in LEVELS:
        say(f"Choose one of: {', '.join(LEVELS)}.")
        return 2
    if not (data_dir() / "config.toml").exists():
        say(f"Memory is not set up yet: run {COMMAND} setup first.")
        return 1
    if level is None:  # just say what it sees, and how to change it
        now = current_level(app) or "what the memory service decides"
        if keyless(app):  # as the engine's `clients` says it
            now += " (work only until it has a key)"
        say(f"{NAMES.get(app, app.capitalize())} sees {now}. To change it: {COMMAND} access {app} "
            f"{' | '.join(LEVELS)}")
        return 0
    if app != "cursor" and level in WIDER:
        say(f"Only Cursor can be widened from here for now. In Claude Code, say \"let {app} see everything\".")
        return 1
    label = NAMES.get(app, app.capitalize())
    if widens(app, level):  # needs the person: the engine's gate decides, before any key is made
        if (marker := agent_shell()):
            say(f"Refused: this is an AI app's shell ({marker} is set). Widening what {label} sees needs you: run "
                f"{COMMAND} access {app} {level} yourself, in a Terminal window.")
            return 1
        if not engine_widens(engine, app, level):
            say(f"Not changed: {label} still sees {current_level(app) or 'what it saw'}.")
            return 1
        if app == "cursor" and level in WIDER:
            record = install_record.load() or install_record.empty()  # so uninstall puts Cursor's files back too
            widened = widen_cursor(engine, record, say=say)
            install_record.save(record)
            if not widened:
                return 1
    elif not set_level(engine, app, level):
        say(f"The memory service did not take the change; {COMMAND} doctor says why.")
        return 1
    say(f"{label} now sees {SAYS[level]}." +
        (" Restart Cursor to load it." if app == "cursor" and level in WIDER else ""))
    return 0

