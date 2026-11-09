"""setup: connect Claude Code, Codex and Cursor to one memory on this Mac (spec 9.2).

The questions come first, as plain text: what it does and changes, consent, the name, the background model, the
import. Nothing is changed before the user says yes. Then the setup screen (screen.py) shows the real work, step by
step: Claude Code, Search models, Memory service, Your apps, Your notes, Self-check. Everything changed goes into
install.json as it happens, so uninstall can put it back even after a failed or interrupted run.
"""
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import tempfile
import textwrap
import time
from importlib import metadata
from pathlib import Path

from . import apps, backend, edits, install_record, keychain, launchd, models, prompt, settings, sockets
from .brand import COMMAND, PRODUCT
from .layout import (CLI_DIST, CONNECTOR_VERSION, ENGINE, ENGINE_DIST, MARKETPLACE, SERVER, data_dir,
                     engine_bin, engine_record, home, on_shell_path, path_advice, short, uv_bin)
from .run import run
from .screen import AppResult, Memory, Step, pick_memory, self_check_row

MIN_DISK = 1_000_000_000
SENSE_DISK = 2_000_000_000   # below this much free space the optional sense model is skipped
READY_WAIT = 20.0


def onboarding():
    """What it does and what it changes, before anything changes (spec 8, wrapped at 78 columns)."""
    return f"""\
{PRODUCT} gives Claude Code, Codex and Cursor one shared memory on this Mac.

Your memory is one file here, never uploaded. After a Claude Code session goes
quiet, your own model (your Claude plan or API key) reads the conversation and
keeps what is worth remembering. Nothing goes to LF Labs. No usage data, ever.

Setup adds {PRODUCT} to Claude Code, Codex and Cursor, backing up every file it
touches, and starts a small background service that keeps search fast.
"{COMMAND} uninstall" puts everything back.
"""


# ---------- before anything changes ----------

def macos_version():
    v = platform.mac_ver()[0]
    return tuple(int(x) for x in v.split(".")[:2]) if v else (0, 0)


def first_name():
    r = run(["id", "-F"], timeout=5)
    words = r.out.strip().split() if r.ok else []
    return words[0] if words else ""


def other_engine():
    """The text an engine answers on the connector socket when it is not this install's own service, else None."""
    got = sockets.ping_connector()
    if not got:
        return None
    is_loaded, pid = launchd.loaded()
    return None if is_loaded and pid else got


def preflight(say):
    """Problems that stop setup before it changes anything (each also a doctor check). [] when all is well."""
    problems = []
    if platform.system() == "Darwin" and macos_version() < (14, 0):
        problems.append(f"{PRODUCT} needs macOS 14 or later.")
    other = other_engine()
    if other:
        problems.append(f"Another memory engine is already running on this Mac ({other}). Stop it first, or set "
                        f"{PRODUCT} up in a separate macOS user account.")
    free = shutil.disk_usage(home()).free
    if free < MIN_DISK:
        problems.append(f"{PRODUCT} needs 1 GB of free disk space (this Mac has {free / 1e9:.1f} GB).")
    if not uv_bin():
        say(f"Note: uv is not on PATH, so `{COMMAND} update` and `{COMMAND} uninstall` will ask you to install it.")
    return problems


def node_problem():
    """What setup's last screen says instead of its success line when the apps cannot start memory's tools (every
    app's MCP entry runs the connector with npx), else None."""
    problem = apps.node_status()[1]
    return f"{problem}: your apps cannot use memory's tools until you {apps.NODE_FIX}." if problem else None


class Answers:
    def __init__(self):
        self.name = ""
        self.backend = "none"
        self.model = "haiku"
        self.claude = None            # backend.Status from the check
        self.api_key = None
        self.import_notes = True
        self.codex_sessions = False
        self.apps = list(apps.DEFAULT)
        self.cursor_personal = False  # Cursor starts at work only unless the user says yes


def ask(args, say):
    """The answers, from flags first, then questions (--yes takes the defaults)."""
    a = Answers()
    yes = True if args.yes else None
    a.model = getattr(args, "model", None) or "haiku"
    a.codex_sessions = bool(args.codex_sessions)
    a.name = first_name() if args.yes else prompt.text("What should your AI apps call you?", first_name())
    a.claude = backend.claude_status(a.model, ping=not args.dry_run) if shutil.which("claude") else \
        backend.Status("claude-cli", False, note="not installed")  # a dry run runs nothing, not even the ping
    # Plan first (Hao, 2026-10-28): the user's Claude plan whenever Claude Code is there, logged in or not; an API key
    # only when the user says yes to it, never as a fallback.
    if args.backend:
        a.backend = args.backend
        if a.backend == "claude-cli" and not a.claude.usable:
            say(f"Claude Code cannot be used for memory's background reading: {a.claude.note}.")
            a.backend = "none"
    elif a.claude.usable and prompt.yes_no("Use your Claude plan for memory's background reading?", True,
                                           assume=yes):
        a.backend = "claude-cli"
    elif not args.yes and prompt.yes_no("Use an Anthropic API key instead?", False):
        key = prompt.secret("Paste your Anthropic API key (it is kept in your Keychain only):")
        ok, note = backend.api_ping(key, a.model) if key else (False, "no key given")
        if ok:
            a.backend, a.api_key = "anthropic-api", key
        else:
            say(f"That key did not work ({note}).")
    if a.backend == "claude-cli" and a.claude.logged_in is False:
        say("Claude Code is not logged in yet: run claude, then /login. Memory starts reading once you do.")
    if a.backend == "none":
        say(f"Memory will run without a model: {backend.NONE_LOSES}. `{COMMAND} setup` again to add one later.")
    if args.only:
        a.apps = [x.strip() for x in args.only.split(",") if x.strip()]
    if "cursor" in a.apps and apps.installed("cursor"):
        a.cursor_personal = prompt.yes_no(f"Let Cursor see your personal notes too? (Change it any time: {COMMAND} "
                                          "access cursor work)", False, assume=False if args.yes else None)
    if args.no_import or not list(claude_notes()):
        a.import_notes = False
    else:
        a.import_notes = prompt.yes_no("Import the notes Claude Code already keeps in ~/.claude/projects/*/memory?",
                                       True, assume=yes)
    return a


# ---------- the notes Claude Code keeps ----------

KIND_SECTION = {"feedback": "prefs", "project": "projects", "reference": "reference", "user": "personal"}


def claude_notes():
    yield from sorted((home() / ".claude/projects").glob("*/memory/*.md"))


def read_note(path):
    """Memory(text, kind, section) from a Claude Code memory file's frontmatter (type: feedback, ...) and body."""
    text = path.read_text(errors="replace")
    kind, body = "note", text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
    if m:
        t = re.search(r"(?m)^\s*type:\s*([A-Za-z]+)", m.group(1))
        kind, body = (t.group(1).lower() if t else "note"), m.group(2)
    return Memory(body.strip(), kind, KIND_SECTION.get(kind, "personal"), created=path.stat().st_mtime)


def memory_moment():
    notes = []
    for p in claude_notes():
        if p.name.upper() != "MEMORY.MD":
            try:
                notes.append(read_note(p))
            except OSError:
                continue
    return pick_memory(notes), len(notes)


# ---------- the work, shown on the setup screen ----------

class RealSetup:
    """plan() / expect_apps / run(ui): the interface screen.py's demo uses too."""

    def __init__(self, answers, record, say, dry=False):
        self.a, self.record, self.say = answers, record, say
        self.engine = engine_bin() or ENGINE
        self.left_alone = []        # (app, path, note, snippet): printed after the screen
        self.connected = []
        self.expect_apps = sum(1 for x in self.a.apps if x in apps.LABELS and apps.installed(x))

    def plan(self):
        return [Step("Claude Code"), Step("Search models", weight=3), Step("Memory service"),
                Step("Your apps", weight=2, apps=True), Step("Your notes"), Step("Self-check")]

    def save(self):
        install_record.save(self.record)

    def run(self, ui):
        self.step_claude(ui)
        if not self.step_models(ui) or not self.step_service(ui):
            return False
        self.step_apps(ui)
        self.step_notes(ui)
        return self.step_check(ui)

    def step_claude(self, ui):
        ui.step("Claude Code", "running")
        c = self.a.claude
        if self.a.backend == "claude-cli" and c.logged_in is False:
            ui.step("Claude Code", "warn", "found; log in to start reading (claude, then /login)")
            return
        if self.a.backend == "claude-cli":
            note = "found, logged in"
        elif self.a.backend == "anthropic-api":
            note = "not used: reading with your API key"
        elif c and c.version:
            note = f"found; background reading off ({'not chosen' if c.usable else c.note or 'not chosen'})"
        else:
            note = "not found; background reading off"
        ui.step("Claude Code", "ok" if self.a.backend != "none" or (c and c.version) else "warn", note)

    def step_models(self, ui):
        ui.step("Search models", "running")
        man = models.manifest()
        if man is None:
            ui.step("Search models", "failed", "the engine has no models list: reinstall with the install line")
            return False
        names = [n for n in man["models"] if n not in models.OPTIONAL or shutil.disk_usage(home()).free >= SENSE_DISK]
        total = models.total_size(man, names)
        try:
            models.download(man, names, lambda done, tot: ui.step("Search models", "running", progress=(done, tot)))
        except models.ChecksumError as e:
            ui.step("Search models", "failed", str(e))
            return False
        except OSError:
            ui.step("Search models", "failed", "the download stopped: check the connection, then run setup again")
            return False
        ui.step("Search models", "ok", f"{total / 1e6:.0f} MB, checked")
        return True

    def step_service(self, ui):
        ui.step("Memory service", "running")
        ran = launchd.install(self.engine)
        for argv, ok, _ in ran:
            install_record.add_command(self.record, argv, ok)
        self.record["plist"] = str(launchd.plist_path())
        self.save()
        _, ok, note = ran[-1]  # the bootstrap
        if not ok:
            ui.step("Memory service", "failed", f"did not start: {note}")
            return False
        if not launchd.wait_ready(READY_WAIT):
            ui.step("Memory service", "failed", "did not start: see ~/Library/Logs/LF Labs/memory.log")
            return False
        ui.step("Memory service", "ok", "running")
        return True

    def step_apps(self, ui):
        ui.step("Your apps", "running")
        order = [x for x in self.a.apps if x in apps.LABELS and apps.installed(x)]
        shown = [AppResult(apps.LABELS[x]) for x in order]
        for app, row in zip(order, shown):
            row.status = "running"
            ui.apps(shown)
            how, hint, ok = getattr(self, f"wire_{app.replace('-', '_')}")()
            row.how, row.hint, row.status = how, hint, "ok" if ok else "failed"
            if ok:
                self.connected.append(row.name)
            ui.apps(shown)
        note = "connected" if self.connected else "none found"
        ui.step("Your apps", "ok" if len(self.connected) == len(order) else "warn", note)

    def _apply(self, plans):
        """Apply file plans. (changed anything, all fine)."""
        changed, fine = False, True
        for p in plans:
            if p.state == "add":
                try:
                    apps.apply(p, self.record)
                    changed = True
                except edits.Skip as e:
                    self.left_alone.append((p.app, p.path, str(e), p.snippet))
                    fine = False
            elif p.state in ("error", "stale"):
                self.left_alone.append((p.app, p.path, p.note, p.snippet))
                fine = False
        self.save()
        return changed, fine

    def _cmd(self, argv, timeout=120):
        r = run(argv, timeout=timeout)
        install_record.add_command(self.record, argv, r.ok)
        self.save()
        return r

    def wire_claude_code(self):
        listed = run(["claude", "plugin", "list"], timeout=30)
        if listed.ok and SERVER in listed.out:
            return "plugin", None, True
        if os.path.isabs(self.engine):  # the plugin's hooks run this path (plugin/scripts/engine), never PATH's
            engine_record().write_text(self.engine + "\n")
        if self._cmd(["claude", "plugin", "marketplace", "add", apps.marketplace_source(), "--scope", "user"]).ok and \
                self._cmd(["claude", "plugin", "install", f"{SERVER}@{MARKETPLACE}", "--scope", "user", "-y"]).ok:
            return "plugin", None, True
        # fallback: the MCP entry by claude mcp add, the hooks in settings.json
        if run(["claude", "mcp", "get", SERVER], timeout=30).ok:
            mcp_ok = True
        else:
            mcp_ok = self._cmd(["claude", "mcp", "add", "--scope", "user", "--transport", "stdio", SERVER, "--", "npx",
                                *apps.connector_args()]).ok
        _, fine = self._apply(apps.file_plans("claude-code", self.engine))
        return "MCP + hooks", None, mcp_ok and fine

    def wire_codex(self):
        changed, fine = self._apply(apps.file_plans("codex", self.engine))
        return "MCP + hook", apps.HINTS["codex"] if changed else None, fine

    def wire_cursor(self):
        changed, fine = self._apply(apps.file_plans("cursor", self.engine))
        if not (fine and self.a.cursor_personal):
            return "MCP", apps.HINTS["cursor"] if changed else None, fine
        from . import access  # the key goes into Cursor's own files and the engine keeps its hash; never shown
        widened = access.widen_cursor(self.engine, self.record,
                                      say=lambda s: self.left_alone.append(("cursor", None, s, ""))) and \
            access.set_level(self.engine, "cursor", "everything")
        self.save()
        return ("MCP (all)" if widened else "MCP"), apps.HINTS["cursor"], True

    def step_notes(self, ui):
        ui.step("Your notes", "running")
        if not self.a.import_notes:
            ui.step("Your notes", "ok", "not imported")
            return
        mem, n = memory_moment()
        r = run([self.engine, "import"], timeout=300)
        if not r.ok:
            ui.step("Your notes", "warn", "could not import them now; the service tries again weekly")
            return
        ui.memory(mem)
        ui.step("Your notes", "ok", f"{n} imported from Claude Code")

    def step_check(self, ui):
        ui.step("Self-check", "running")
        ok, seconds, why = self_check(self.engine)
        if not ok:
            ui.step("Self-check", "failed", why)
            return False
        ui.step("Self-check", *self_check_row(seconds))
        return True


def _hook(engine, sub, payload, client=None):
    env = dict(os.environ)
    if client:
        env["LFLABS_MEMORY_CLIENT"] = client
    t0 = time.monotonic()
    r = run([engine, sub], input=json.dumps(payload), timeout=15, env=env)
    took = time.monotonic() - t0
    try:
        out = json.loads(r.out) if r.out.strip() else {}
    except ValueError:
        out = {"text": r.out}
    return r.ok, took, out


def _context(out):
    if not isinstance(out, dict):
        return ""
    spec = out.get("hookSpecificOutput") or {}
    return str(spec.get("additionalContext") or out.get("additional_context") or out.get("text") or "")


def self_check(engine):
    """(passed, recall seconds, why it failed): the try-it path end to end (spec 9.2 step 9)."""
    with tempfile.TemporaryDirectory(prefix="lflabs-check-") as d:
        project = Path(d) / "check-project"
        project.mkdir()
        subprocess.run(["git", "init", "-q", str(project)], capture_output=True, timeout=15)
        sid = f"self-check-{secrets.token_hex(4)}"
        base = {"session_id": sid, "transcript_path": str(project / "t.jsonl"), "cwd": str(project),
                "hook_event_name": "UserPromptSubmit"}
        ok, took, _ = _hook(engine, "hook-prompt", {**base, "prompt": "what do we know about this project?"})
        if not ok:
            return False, took, "the prompt hook failed: see ~/Library/Logs/LF Labs/memory.log"
        word = secrets.token_hex(3)
        fact = f"{COMMAND} self-check {word}"
        ok, _, out = _hook(engine, "hook-prompt", {**base, "session_id": sid + "b", "prompt": f"remember that {fact}"})
        saved = re.search(r"\(#(\d+)\)", _context(out))
        if not ok or not saved or fact not in _context(out):
            return False, took, "a typed \"remember that\" was not saved"
        mid = saved.group(1)
        try:
            ok, _, out = _hook(engine, "hook-cursor-start", {"hook_event_name": "sessionStart", "workspace_roots":
                                                             [str(project)], "cwd": str(project)}, client="cursor")
            if not ok or word not in _context(out):
                return False, took, "a new Cursor chat would not see it"
            got = sockets.ask("recall", {"query": fact, "k": 5}, client="cursor")
            if not got.get("ok") or word not in (got.get("text") or ""):
                return False, took, "the memory service did not answer" if not got.get("ok") else \
                    "Codex and Cursor could not recall it"
        finally:
            run([engine, "purge", mid], timeout=30)  # gone for good, not just retired
    return True, took, ""


# ---------- the command ----------

def dry_run(a, say):
    """Every file and command setup would touch, with the exact lines; nothing is written or run."""
    eng = engine_bin() or ENGINE
    say("A dry run: nothing is changed. Setup would:\n")
    say(f"  write {short(settings.path())} (0600):")
    say(textwrap.indent(settings.render(a.name, a.backend, a.model, a.codex_sessions), "      "))
    say(f"  download the search models into {short(models.folder())}")
    say(f"  write {short(launchd.plist_path())} and run: launchctl bootstrap {launchd.domain()} "
        f"{short(launchd.plist_path())}")
    for app in a.apps:
        if app not in apps.LABELS or not apps.installed(app):
            say(f"\n  {apps.LABELS.get(app, app)}: not installed, skipped")
            continue
        say(f"\n  {apps.LABELS[app]}:")
        if app == "claude-code":
            say(f"    run: claude plugin marketplace add {apps.marketplace_source()} --scope user")
            say(f"    run: claude plugin install {SERVER}@{MARKETPLACE} --scope user -y")
            say("    (if those fail: claude mcp add, and these hooks in ~/.claude/settings.json)")
        for p in apps.file_plans(app, eng):
            say(f"    {short(p.path)}: {p.note}")
            if p.snippet and p.state != "done":
                say(textwrap.indent(p.snippet.rstrip("\n"), "      "))
    if "cursor" in a.apps and apps.installed("cursor"):
        say("\n  Cursor sees " + ("everything, personal notes too (a key in its two files)" if a.cursor_personal
                                  else "work notes only"))
    if a.import_notes:
        say(f"\n  import {len(list(claude_notes()))} notes from ~/.claude/projects/*/memory")
    say(f"\n  record every change in {short(install_record.install_json())}")
    return 0


def main(args, say=print):
    from .main import full_show, play
    if args.dry_run:
        say(onboarding())
        return dry_run(ask(args, say), say)
    say(onboarding())
    if not prompt.yes_no("Continue?", True, assume=True if args.yes else None):
        say("Nothing was changed.")
        return 0
    problems = preflight(say)
    if problems:
        for p in problems:
            say(p)
        return 1
    node = node_problem()
    if node:
        say(f"Note: {node}")
    a = ask(args, say)
    record = install_record.load() or install_record.empty()
    intro = full_show(args.show)
    data_dir().mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(data_dir(), 0o700)
    if a.api_key and keychain.store(a.api_key):
        record["keychain"] = True
    settings.save(settings.render(a.name, a.backend, a.model, a.codex_sessions))
    record["versions"] = {"cli": _version(CLI_DIST), "engine": _version(ENGINE_DIST), "connector": CONNECTOR_VERSION}
    install_record.save(record)
    work = RealSetup(a, record, say)
    work.problem = node
    code = play(work, intro=intro, plain=args.plain, animate=not args.no_animation)
    for app, path, note, snippet in work.left_alone:
        say(f"\n{apps.LABELS.get(app, app)}: {short(path) + ': ' if path else ''}{note}")
        if snippet:
            say(textwrap.indent(snippet.rstrip("\n"), "    "))
    if code == 0:
        model = backend.MODELS.get(a.model, a.model)
        say({"claude-cli": f"Background reading: your Claude plan ({model}), up to {settings.DEFAULTS['llm']['daily_calls']} calls a day",
             "anthropic-api": f"Background reading: your Anthropic API key ({model}), up to "
                              f"{settings.DEFAULTS['llm']['daily_calls']} calls a day",
             "none": f"Background reading: off ({backend.NONE_LOSES})"}[a.backend])
        say(f"`{COMMAND} doctor` checks everything. `{COMMAND} uninstall` removes it all.")
    if not on_shell_path():
        say("\n" + path_advice())
    return code


def _version(dist):
    try:
        return metadata.version(dist)
    except metadata.PackageNotFoundError:
        return None


