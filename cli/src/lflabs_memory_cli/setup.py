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
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import time
from importlib import metadata
from pathlib import Path

from . import (access, apps, backend, claude_settings, edits, install_record, keychain, launchd, layout, models,
               prompt, screen, settings, sockets)
from .brand import COMMAND, PRODUCT, REPO
from .layout import (CLI_DIST, CONNECTOR_VERSION, ENGINE, ENGINE_DIST, MARKETPLACE, SERVER, data_dir,
                     engine_bin, engine_record, find_claude, git_available, home, lf_labs_dir, on_shell_path, path_advice, short, uv_bin)
from .run import run
from .screen import AppResult, Memory, Step, pick_memory, self_check_row

MIN_DISK = 1_000_000_000
SENSE_DISK = 2_000_000_000   # below this much free space the optional sense model is skipped
READY_WAIT = 20.0


def onboarding():
    """What it does and what it changes, before anything changes (spec 8, wrapped at 78 columns)."""
    return f"""\
{PRODUCT} gives Claude Code, Codex and Cursor one shared memory on this Mac.

Your memory is one file here, never uploaded to us. After a Claude Code
session goes quiet, your own model (your Claude plan or API key) reads the
conversation and keeps what is worth remembering. Nothing goes to LF Labs. No
usage data, ever.

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
    known = settings.load().get("owner_name") or first_name()  # a re-run keeps the name given before
    a.name = known if args.yes else prompt.text("What should your AI apps call you?", known)
    a.claude = backend.claude_status(a.model, ping=not args.dry_run) if shutil.which("claude") else \
        backend.Status("claude-cli", False, note="not installed")  # a dry run runs nothing, not even the ping
    # Plan first (decided 2026-10-28): the user's Claude plan whenever Claude Code is there, logged in or not; an API key
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
    if "cursor" in a.apps and apps.installed("cursor") and not access.agent_shell():  # never offered to an agent
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
        # The Claude Code notes this setup run imports (trust_imported): the service imports them too as it starts, before
        # the notes step, so what counts is what is new since setup began.
        self.imported, self.notes_before, self.import_since = [], None if dry else _max_id(), time.time()
        self.models_missing = []    # required models the download could not get
        self.connected = []
        self.expect_apps = sum(1 for x in self.a.apps if x in apps.LABELS and apps.installed(x))

    def plan(self):
        return [Step("Claude Code"), Step("Search models", weight=3), Step("Memory service"),
                Step("Your apps", weight=2, apps=True), Step("Your notes"), Step("Self-check")]

    def save(self):
        install_record.save(self.record)

    def run(self, ui):
        self.step_claude(ui)
        if not self.step_models(ui):
            return False
        if self.models_missing:  # the engine will not start without them: connect the apps, finish later
            ui.step("Memory service", "warn", "waits for the models")
            self.step_apps(ui)
            ui.step("Your notes", "warn", "waits for the models")
            ui.step("Self-check", "warn", "waits for the models")
            if hasattr(ui, "state"):
                ui.state.problem = (f"The search models could not be downloaded, so memory is not running yet. Your "
                                    f"apps are connected: run {COMMAND} setup --models to finish.")
            return False
        if not self.step_service(ui):
            return False
        self.step_apps(ui)
        self.step_notes(ui)
        return self.step_check(ui)

    def step_claude(self, ui):
        ui.step("Claude Code", "running")
        c = self.a.claude
        if self.a.backend == "claude-cli" and c.logged_in is False:
            ui.step("Claude Code", "warn", "found; log in to start: claude, then /login")
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
        except (models.ChecksumError, OSError):  # retried and resumed already; what is got stays for next time
            self.models_missing = [n for n, s in models.check(man, names=names).items() if s != "ok"] or names
            ui.step("Search models", "warn", f"{', '.join(self.models_missing)} missing: {COMMAND} setup --models")
            return True
        ui.step("Search models", "ok", f"{total / 1e6:.0f} MB, checked")
        return True

    def step_service(self, ui):
        ui.step("Memory service", "running")
        ok, why = start_service(self.engine, self.record,
                                lambda s: ui.step("Memory service", "running", s))
        self.save()
        if not ok:
            ui.step("Memory service", "failed", why)
            return False
        ui.step("Memory service", "ok", "running")
        return True

    def step_apps(self, ui):
        ui.step("Your apps", "running")
        from .update import bump_pins  # an earlier setup's Codex and Cursor entries move to this connector version
        bump_pins(lambda s: None, self.record)
        self.save()
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
        if len(self.connected) == len(order):
            note = "connected" if order else "none found"
        else:  # found, but not all of them could be connected: each row's hint says what is left
            note = f"{len(self.connected)} of {len(order)} connected"
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
            if apps.marketplace_pinned():
                self._drop_fallback()
                return "plugin", None, True
            # an older install's marketplace (main's head, or another tag): its ref cannot be changed in place, so
            # remove it (that uninstalls the plugin too) and add it at this release's tag, as update does
            self._cmd(["claude", "plugin", "marketplace", "remove", MARKETPLACE])
        if os.path.isabs(self.engine):  # the plugin's hooks run this path (plugin/scripts/engine), never PATH's
            engine_record().write_text(self.engine + "\n")
        if self._cmd(["claude", "plugin", "marketplace", "add", apps.marketplace_source(), "--scope", "user"]).ok and \
                self._cmd(["claude", "plugin", "install", f"{SERVER}@{MARKETPLACE}", "--scope", "user", "-y"]).ok:
            self._drop_fallback()
            return "plugin", None, True
        # fallback: the MCP entry by claude mcp add, the hooks in settings.json
        if run(["claude", "mcp", "get", SERVER], timeout=30).ok:
            mcp_ok = True
        else:
            mcp_ok = self._cmd(["claude", "mcp", "add", "--scope", "user", "--transport", "stdio", SERVER, "--", "npx",
                                *apps.connector_args()]).ok
        _, fine = self._apply(apps.file_plans("claude-code", self.engine))
        return "MCP + hooks" if mcp_ok else "hooks", None, mcp_ok and fine

    def _drop_fallback(self):
        """With the plugin installed, an earlier setup's fallback (its hooks in ~/.claude/settings.json, its MCP entry
        by `claude mcp add`) would run every hook twice and list memory's tools twice: take out what install.json
        says setup added, as uninstall does."""
        from . import uninstall
        for entry in [f for f in self.record["files"] if f.get("kind") == "claude-settings"]:
            uninstall._file(entry, uninstall.Report(lambda s: None))
            self.record["files"].remove(entry)
        added = any(c.get("ok") and c["argv"][1:3] == ["mcp", "add"] for c in self.record["commands"])
        if added and run(["claude", "mcp", "get", SERVER], timeout=30).ok:
            self._cmd(["claude", "mcp", "remove", "--scope", "user", SERVER])
        self.save()

    def wire_codex(self):
        changed, fine = self._apply(apps.file_plans("codex", self.engine))
        return "MCP + hook", apps.HINTS["codex"] if changed else None, fine

    def wire_cursor(self):  # work only: a yes to personal notes is confirmed after the screen (access.main)
        changed, fine = self._apply(apps.file_plans("cursor", self.engine))
        return "MCP", apps.HINTS["cursor"] if changed else None, fine

    def step_notes(self, ui):
        ui.step("Your notes", "running")
        if not self.a.import_notes:
            ui.step("Your notes", "ok", "not imported")
            return
        mem, _ = memory_moment()
        r = run([self.engine, "import"], timeout=300)
        if not r.ok:
            ui.step("Your notes", "warn", "could not import them now; the service tries again weekly")
            return
        self.imported = _imported_ids(self.notes_before)
        ui.memory(mem)
        k = len(self.imported)  # this run's new notes; n counts every memory file, already imported ones too
        ui.step("Your notes", "ok", f"{k} imported from Claude Code" if k else "nothing new from Claude Code")

    def step_check(self, ui):
        ui.step("Self-check", "running")
        if apps.connector_on_npm() is False and hasattr(ui, "state"):
            ui.state.problem = f"Setup is done, but {apps.NOT_ON_NPM}. Run {COMMAND} doctor once it is published."
        ok, seconds, why = checked(self.engine)
        if not ok:
            ui.step("Self-check", "failed", why)
            return False
        if why.startswith(KEPT):  # never purge a memory the check did not make
            ui.step("Self-check", "warn", f"{self_check_row(seconds)[1]}; {why} (not new)")
            return True
        if why == NO_GIT:
            ui.step("Self-check", "warn", f"{self_check_row(seconds)[1]}; git missing (see below)")
            self.left_alone.append(("Self-check", None, NO_GIT_NOTE, ""))
            return True
        ui.step("Self-check", *self_check_row(seconds))
        return True


CHECK_TRIES, CHECK_GAP = 3, 2.0


def ready(timeout=None):
    """The service answers: both its sockets (launchd.wait_ready), then a real recall on the connector."""
    timeout = READY_WAIT if timeout is None else timeout
    end = time.monotonic() + timeout
    if not launchd.wait_ready(timeout):
        return False
    while not sockets.ask("recall", {"query": "ready", "k": 1}, client="cursor").get("ok"):
        if time.monotonic() >= end:
            return False
        time.sleep(0.25)
    return True


def checked(engine):
    """self_check once the service is ready, tried up to CHECK_TRIES times CHECK_GAP s apart: a service that has
    just started can miss the first probe (macOS 26 runners, 2 of 7)."""
    ready()
    for n in range(CHECK_TRIES):
        got = self_check(engine)
        if got[0] or n + 1 == CHECK_TRIES:
            return got
        time.sleep(CHECK_GAP)


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


NO_GIT = "git does not work"
NO_GIT_NOTE = ("git does not work on this Mac: install Apple's Command Line Tools (xcode-select --install). Until "
               "then memory finds a repo by its .git folder, and only inside your home folder.")


def self_check(engine):
    """(passed, recall seconds, why it failed): the try-it path end to end (spec 9.2 step 9), in a new repo. Without
    the Command Line Tools git is never run (its stub would put up a dialog: layout.git_available): the repo is a .git
    folder made by hand, in the home folder (where the engine finds repos without git) for the few seconds it takes,
    and why is NO_GIT with passed True."""
    git = git_available()
    with tempfile.TemporaryDirectory(prefix="lflabs-check-", dir=None if git else home()) as d:
        project = Path(d).resolve() / "check-project"
        project.mkdir()
        if git:
            subprocess.run(["git", "init", "-q", str(project)], capture_output=True, timeout=15)
        else:
            (project / ".git").mkdir(mode=0o700)
        sid = f"self-check-{secrets.token_hex(4)}"
        base = {"session_id": sid, "transcript_path": str(project / "t.jsonl"), "cwd": str(project),
                "hook_event_name": "UserPromptSubmit"}
        ok, took, _ = _hook(engine, "hook-prompt", {**base, "prompt": "what do we know about this project?"})
        if not ok:
            return False, took, "the prompt hook failed: see ~/Library/Logs/LF Labs/memory.log"
        fact = check_phrase()
        word = fact.split()[-1]
        before = _max_id()
        typed = {**base, "session_id": sid + "b", "prompt": f"remember that {fact}"}
        made = _typed_transcript(typed)  # where Claude Code would write this session's transcript
        try:
            ok, _, out = _hook(engine, "hook-prompt", typed)
            saved = re.search(r"\(#(\d+)\)", _context(out))
            if not ok or not saved or fact not in _context(out):
                return False, took, "a typed \"remember that\" was not saved"
            # Other apps get a typed save once memory finds it as the user's own turn in the transcript (at the reply's
            # end, or the session's next prompt): the turn is written there and the next prompt sent, as Claude Code
            # would.
            Path(typed["transcript_path"]).write_text(json.dumps({
                "type": "user", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                "sessionId": typed["session_id"], "uuid": secrets.token_hex(16),
                "message": {"role": "user", "content": typed["prompt"]}}) + "\n")
            _hook(engine, "hook-prompt", {**typed, "prompt": "ok"})
        finally:
            for i, x in enumerate(made):  # what this made, newest first: its own folder, then any parent it had to
                try:  # make, only if still empty (Claude Code may have started meanwhile)
                    shutil.rmtree(x) if i == 0 else x.rmdir()
                except OSError:
                    pass
        mid = saved.group(1)
        new = before is not None and int(mid) > before  # made by this check, not an older memory it merged into
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
            if new:  # only the exact memory this check made, gone for good
                run([engine, "purge", mid], timeout=30)
    if not new:
        return True, took, f"{KEPT}{mid}"
    return True, took, "" if git else NO_GIT


def _typed_transcript(typed):
    """Sets typed["transcript_path"] to a new session folder under ~/.claude/projects, as Claude Code names its
    transcripts, and makes it: the folders it made, newest first, for the caller to remove."""
    made, d = [], home() / ".claude" / "projects" / f"-{COMMAND}-self-check-{secrets.token_hex(4)}"
    for x in (d.parent.parent, d.parent, d):
        if not x.exists():
            x.mkdir(mode=0o700)
            made.insert(0, x)
    typed["transcript_path"] = str(d / f"{typed['session_id']}.jsonl")
    return made


KEPT = "kept #"  # self_check's why when the save landed in a memory that was there before: not purged
WORDS = ("amber", "basil", "cedar", "delta", "copper", "fjord", "garnet", "harbor", "indigo", "juniper", "kelp",
         "lantern", "maple", "nectar", "meadow", "pebble", "quartz", "ridge", "saffron", "thistle", "orchard", "falcon",
         "willow", "canyon", "zephyr", "anvil", "birch", "cobalt", "dune", "estuary", "fennel", "gravel")


def check_phrase():
    """What the self-check saves: five random words and a random number, nothing like any real memory (an older
    "<command> self-check <hex>" was taken as a restatement and merged, then purged with it). Every word is a common
    one, so the save is never held back for review and the check sees it at once."""
    return " ".join(secrets.choice(WORDS) for _ in range(5)) + f" {secrets.randbelow(10 ** 6):06d}"


def _imported_ids(before):
    """The ids of the Claude Code notes an import just made: newer than before (_max_id), from a memory file, not yet
    trusted; [] when the store cannot be read."""
    p = data_dir() / "memory.db"
    if before is None or not p.exists():
        return []
    try:
        db = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
        try:
            return [r[0] for r in db.execute(
                "select id from memories where id > ? and status = 'active' and coalesce(origin, 'unknown') ="
                " 'unknown' and source glob '*/.claude/projects/*/memory/*.md' order by id", (before,))]
        finally:
            db.close()
    except sqlite3.Error:
        return []


def can_ask_in_person(args):
    """A person at this Terminal to answer a dialog: not --yes, a real terminal both ways, and no AI app's environment or
    process among this one's ancestors (access.agent_shell, access.agent_ancestor: unreadable counts as one)."""
    return not args.yes and sys.stdin.isatty() and sys.stdout.isatty() and not access.agent_shell() and \
        access.agent_ancestor() is None


def trust_imported(engine, ids, since, args, say):
    """After the screen: the Claude Code notes this setup imported are held like any import until the user trusts them.
    In person, the engine's one macOS dialog (`trust`, its own text and three snippets) asks; else, or on Cancel, say
    how to confirm them later."""
    n = len(ids)
    if can_ask_in_person(args):
        r = run([engine, "trust", "--claude-import-since", repr(since), "--", *map(str, ids)], timeout=300)
        if r.ok and (r.out or "").strip().startswith("trusted"):
            say(f"\nThe {n} note{'s' if n > 1 else ''} you imported from Claude Code {'are' if n > 1 else 'is'} yours "
                f"now: every app may use {'them' if n > 1 else 'it'}.")
            return True
    say(f"\nThe {n} note{'s' if n > 1 else ''} imported from Claude Code {'are' if n > 1 else 'is'} kept for search "
        f"until you confirm {'them' if n > 1 else 'it'}: `{ENGINE} held` lists {'them' if n > 1 else 'it'}, and "
        f"`{ENGINE} trust -- {' '.join(map(str, ids[:8]))}{' ...' if n > 8 else ''}` trusts "
        f"{'them' if n > 1 else 'it'} as yours (it asks in a dialog).")
    return False


def _max_id():
    """The highest memory id in the store before the check saves: 0 with no store yet, None when it cannot be read."""
    p = data_dir() / "memory.db"
    if not p.exists():
        return 0
    try:
        db = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
        try:
            return db.execute("select coalesce(max(id), 0) from memories").fetchone()[0]
        finally:
            db.close()
    except sqlite3.Error:
        return None


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


READY_LONGER, READY_RETRY = 40.0, 30.0  # with READY_WAIT: up to 60 s for a first start, then 30 s after one retry


def start_service(engine, record, note=lambda s: None):
    """(started, why not). A fresh Mac's first start can take long (the models load for the first time, a cold
    disk): wait up to READY_WAIT + READY_LONGER seconds, saying it is still starting; then reload the agent once
    and wait again. When it never answers, memory.log gets why: launchctl's view of it and whether the engine runs."""
    ran = launchd.install(engine)
    for argv, ok, _ in ran:
        install_record.add_command(record, argv, ok)
    record["plist"] = str(launchd.plist_path())
    _, ok, why = ran[-1]  # the bootstrap
    if not ok:
        return False, f"did not start: {why}"
    if launchd.wait_ready(READY_WAIT):
        return True, ""
    note("still starting: a first start loads the models")
    if launchd.wait_ready(READY_LONGER):
        return True, ""
    for argv, ok, _ in launchd.restart():
        install_record.add_command(record, argv, ok)
    if launchd.wait_ready(READY_RETRY):
        return True, ""
    _log_no_start(engine)
    return False, "did not start: see ~/Library/Logs/LF Labs/memory.log"


def _log_no_start(engine):
    """What setup knows when the service never answered, appended to memory.log (it was empty in the VMs)."""
    shown = run(["launchctl", "print", f"{launchd.domain()}/{launchd.LABEL}"], timeout=30)
    ver = run([engine, "--version"], timeout=60)
    lines = [f"{time.strftime('%Y-%m-%d %H:%M:%S')} setup: the memory service did not answer within "
             f"{READY_WAIT + READY_LONGER + READY_RETRY:.0f} s (one reload included).",
             f"  launchctl print (exit {shown.code}):"] + \
        [f"    {x}" for x in (shown.out or shown.err).strip().splitlines()[:40]] + \
        [f"  {engine} --version (exit {ver.code}): {(ver.out or ver.err).strip()[:300]}"]
    log = layout.logs_dir() / "memory.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a") as f:
        f.write("\n".join(lines) + "\n")


def finish_models(say):
    """`setup --models`: the search models a setup could not download (resumed where it stopped), then the memory
    service it could not start without them, and the self-check."""
    if not install_record.load() or not settings.path().exists():
        say(f"Memory is not set up yet: run {COMMAND} setup first.")
        return 1
    man = models.manifest()
    if man is None:
        say("The engine has no models list: reinstall with the install line.")
        return 1
    names = [n for n in man["models"] if n not in models.OPTIONAL or shutil.disk_usage(home()).free >= SENSE_DISK]
    todo = [n for n, s in models.check(man, names=names).items() if s != "ok"]
    if todo:
        say(f"Downloading {', '.join(todo)} ({models.total_size(man, todo) / 1e6:.0f} MB)...")
        try:
            models.download(man, todo)
        except (models.ChecksumError, OSError) as e:
            say(f"Still missing ({e}): check the connection, then run {COMMAND} setup --models again.")
            return 1
    record = install_record.load()
    engine = engine_bin() or ENGINE
    ok, why = start_service(engine, record)
    install_record.save(record)
    if not ok:
        say(f"The memory service {why}")
        return 1
    ok, _, why = checked(engine)
    if not ok:
        say(f"Self-check: {why}")
        return 1
    say("The search models are all here and the memory service is running.")
    return 0


def main(args, say=print):
    from .main import full_show, play
    if getattr(args, "models", False):
        return finish_models(say)
    if args.dry_run:
        say(onboarding())
        return dry_run(ask(args, say), say)
    say(onboarding())
    if not args.yes and not sys.stdin.isatty():  # no one to say yes: consent is never assumed
        say(f"There is no terminal to ask on, so nothing was changed. Run {COMMAND} setup in a Terminal window, or "
            f"{COMMAND} setup --yes to take the defaults.")
        return 1
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
    data_dir().mkdir(parents=True, exist_ok=True, mode=0o700)
    for d in (data_dir(), lf_labs_dir()):  # mkdir's mode is the last folder's only: LF Labs would be 0755
        if d.is_dir():
            os.chmod(d, 0o700)
    claude_settings.snapshot()  # before the first claude command (ask's check): Claude Code rewrites it as it runs
    a = ask(args, say)
    record = install_record.load() or install_record.empty()
    intro = full_show(args.show)
    if a.api_key and keychain.store(a.api_key):
        record["keychain"] = True
    settings.save(settings.render(a.name, a.backend, a.model, a.codex_sessions, claude_path=find_claude(),
                                  keep=settings.raw()))
    record["versions"] = {"cli": _version(CLI_DIST), "engine": _version(ENGINE_DIST), "connector": CONNECTOR_VERSION}
    install_record.save(record)
    work = RealSetup(a, record, say)
    work.problem = node
    code = play(work, intro=intro, plain=args.plain, animate=not args.no_animation)
    if code == 0 and a.cursor_personal:  # widening needs the person to confirm it, here as in `access` itself
        access.main("cursor", "everything", work.engine, say=say)
    if code == 0 and work.imported:  # the notes imported from Claude Code: the person trusts them in a dialog
        trust_imported(work.engine, work.imported, work.import_since, args, say)
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
    if code == 0 and not (args.plain or args.yes) and sys.stdin.isatty() and sys.stdout.isatty():
        star_once(say)
    return code


STAR = f"If {PRODUCT} helps, a star helps others find it: github.com/{REPO}"


def star_once(say):
    """One quiet line, once per Mac: a flag file in the data folder says it was shown (setup run again, or uninstall
    with --keep-data, never shows it again; it goes with the data folder)."""
    flag = data_dir() / ".star-shown"
    if flag.exists():
        return
    grey = screen.detect()["color"]
    say("\n" + screen.IND + (f"\x1b[38;5;{screen.GREY}m{STAR}\x1b[0m" if grey else STAR))
    os.close(os.open(flag, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600))


def _version(dist):
    try:
        return metadata.version(dist)
    except metadata.PackageNotFoundError:
        return None


