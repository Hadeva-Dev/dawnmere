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
# Set in the shells AI apps run their commands in (checked 2026-11): a widening from one is refused outright, since an
# agent there could otherwise widen its own access. Claude Code: seen in its Bash tool's shell (2.1.301). Codex: the
# names its 0.160.0 binary sets for its shell tool and sandbox. Cursor: its agent terminal sets CURSOR_AGENT=1 and
# CURSOR_CONVERSATION_ID, its sandbox CURSOR_SANDBOX (cursor-agent-exec in Cursor.app); not CURSOR_TRACE_ID, which
# every Cursor terminal has, the person's own too.
AGENT_ENV = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT",
             "CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED", "CODEX_THREAD_ID", "CODEX_SESSION_ID", "CODEX_CI",
             "CURSOR_AGENT", "CURSOR_CONVERSATION_ID", "CURSOR_SANDBOX")


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


def _tty():
    return sys.stdin.isatty() and sys.stdout.isatty()


def _ask(question):
    try:
        return input(question)
    except EOFError:
        return ""


def agent_shell(env=None):
    """The first AI-app marker set in this environment, or None."""
    env = os.environ if env is None else env
    return next((k for k in AGENT_ENV if env.get(k)), None)


def person_confirms(app, level, say):
    """Widening needs a person: not an AI app's shell, a terminal on stdin and stdout, and the app's name typed back.
    (A native confirmation dialog would be the next step.)"""
    label = apps.LABELS.get(app, app.capitalize())
    marker = agent_shell()
    if marker:
        say(f"Refused: this is an AI app's shell ({marker} is set). Widening what {label} sees needs you: run "
            f"{COMMAND} access {app} {level} yourself, in a Terminal window.")
        return False
    if not _tty():
        say(f"Widening what {label} sees needs you at a terminal: run {COMMAND} access {app} {level} in a Terminal "
            "window.")
        return False
    if _ask(f"To let {label} see {SAYS[level]}, type {app}: ").strip().lower() != app:
        say("Not confirmed: nothing was changed.")
        return False
    return True


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
        say(f"{apps.LABELS.get(app, app.capitalize())} sees {now}. To change it: {COMMAND} access {app} "
            f"{' | '.join(LEVELS)}")
        return 0
    if app != "cursor" and level in WIDER:
        say(f"Only Cursor can be widened from here for now. In Claude Code, say \"let {app} see everything\".")
        return 1
    if widens(app, level) and not person_confirms(app, level, say):
        return 1
    if app == "cursor" and level in WIDER:
        record = install_record.load() or install_record.empty()  # so uninstall puts Cursor's files back too
        widened = widen_cursor(engine, record, say=say)
        install_record.save(record)
        if not widened:
            return 1
    if not set_level(engine, app, level):
        say(f"The memory service did not take the change; {COMMAND} doctor says why.")
        return 1
    say(f"{apps.LABELS.get(app, app.capitalize())} now sees {SAYS[level]}." +
        (" Restart Cursor to load it." if app == "cursor" and level in WIDER else ""))
    return 0

