"""The command line: setup, doctor, uninstall, export, update; and the engine's memory commands (held, trust, forget,
restore, search, add), run as the engine runs them."""
import argparse
import codecs
import locale
import os
import sys
from pathlib import Path

from . import screen
from .brand import COMMAND, PRODUCT


def data_dir():
    home = os.environ.get("LFLABS_MEMORY_HOME")
    return Path(home) if home else Path.home() / "Library" / "Application Support" / "LF Labs" / "Memory"


def full_show(show=False):
    """The full show (Kip and the wordmark) plays on the first setup (no install.json yet) or with --show; a re-run
    gets the short one."""
    return show or not (data_dir() / "install.json").exists()


def play(setup, intro=True, plain=False, animate=True):
    """Run a setup behind the screen. Returns its exit code."""
    state = screen.ScreenState(steps=setup.plan(), expect_apps=setup.expect_apps, intro=intro,
                               problem=getattr(setup, "problem", None), **screen.detect(plain=plain, animate=animate))
    ui = screen.Animator(state)
    ui.start()
    try:
        ok = setup.run(ui)
    except BaseException:
        ui.abort()
        raise
    ui.finish()
    return 0 if ok else 1


def cmd_setup(args):
    if args.demo:
        from .demo import FakeSetup
        intro = args.demo != "rerun"
        return play(FakeSetup(args.demo), intro=intro, plain=args.plain, animate=not args.no_animation)
    from . import setup
    return setup.main(args)


def cmd_doctor(args):
    from . import doctor
    return doctor.main(as_json=args.json, as_report=args.report, licenses=args.licenses)


def cmd_uninstall(args):
    from . import uninstall
    return uninstall.main(keep_data=args.keep_data)


def cmd_export(args):
    from . import export
    return export.export(args.out, args.format, args.include_claims)


def cmd_import(args):
    from . import export
    return export.import_file(args.file)


def cmd_access(args):
    from . import access
    from .layout import ENGINE, engine_bin
    return access.main(args.app, args.level, engine_bin() or ENGINE)


def cmd_update(args):
    from . import update
    if args.finish:
        return update.finish(args.finish)
    return update.main(check_only=args.check, yes=args.yes)


COMMANDS = {
    "setup": (cmd_setup, "connect your AI apps to one memory on this Mac"),
    "doctor": (cmd_doctor, "check that everything works"),
    "uninstall": (cmd_uninstall, "remove everything setup added"),
    "export": (cmd_export, "save your memory to a file"),
    "import": (cmd_import, "add memories from an export file"),
    "access": (cmd_access, "what each AI app may see (access), or change one: access cursor everything|work"),
    "update": (cmd_update, f"update {PRODUCT}"),
}


# The engine's own commands, under this command's name: the engine runs them in this one's place (exec), with the same
# arguments, terminal, dialogs and exit code. `lflabs-memory COMMAND` keeps working.
FRONT = {
    "held": "app saves held back from prompts, and the line that confirms each",
    "trust": "make memories your own words, after you click Allow in a dialog: trust -- ID...",
    "forget": "delete a memory for good: forget ID",
    "restore": "bring back a memory an app forgot in the last day: restore ID",
    "search": "search your memory: search QUERY",
    "add": "save one memory: add TEXT",
}


def front_door(argv):
    from .layout import engine_bin
    eng = engine_bin()
    if not eng:
        print(f"The memory engine is not installed, so `{COMMAND} {argv[0]}` cannot run. Run the install line again.",
              file=sys.stderr)
        return 1
    os.execv(eng, [eng, *argv])


def version_line():
    """What --version prints: the release, and the engine and connector that go with it."""
    from importlib import metadata

    from .layout import CLI_DIST, CONNECTOR_VERSION, ENGINE_DIST

    def v(dist):
        try:
            return metadata.version(dist)
        except metadata.PackageNotFoundError:
            return "?"
    return f"{PRODUCT} {v(CLI_DIST)} (engine {v(ENGINE_DIST)}, connector {CONNECTOR_VERSION})"


def parser():
    p = argparse.ArgumentParser(prog=COMMAND, description=f"{PRODUCT}: one memory for Claude Code, Codex and Cursor.")
    p.add_argument("--version", action="version", version=version_line())
    sub = p.add_subparsers(dest="command", required=True, metavar="command")
    for name, help_text in FRONT.items():  # listed in --help; main() hands them to the engine before parsing
        sub.add_parser(name, help=help_text, add_help=False).add_argument("args", nargs=argparse.REMAINDER)
    for name, (_, help_text) in COMMANDS.items():
        sp = sub.add_parser(name, help=help_text, description=help_text)
        if name == "setup":
            from .demo import SCENARIOS
            sp.add_argument("--plain", action="store_true", help="plain lines: no art, colour or animation")
            sp.add_argument("--no-animation", action="store_true", help="still frames instead of animation")
            sp.add_argument("--show", action="store_true", help="play the full intro again")
            sp.add_argument("--demo", nargs="?", const="default", choices=SCENARIOS, metavar="SCENARIO",
                            help=f"play the setup screen with fake steps ({', '.join(SCENARIOS)})")
            sp.add_argument("--yes", action="store_true", help="take the defaults (the screen is still shown)")
            sp.add_argument("--backend", choices=("claude-cli", "anthropic-api", "none"))
            sp.add_argument("--model", choices=("haiku", "sonnet"),
                            help="sonnet remembers a few more of your rules, at about 10 times the usage")
            sp.add_argument("--only", help="apps to connect: claude-code,codex,cursor,windsurf,gemini,copilot,qwen-code,kimi-code,qoder,iflow,cline")
            sp.add_argument("--codex-sessions", action="store_true", help="also read Codex's saved sessions")
            sp.add_argument("--no-import", action="store_true", help="do not import Claude Code's memory files")
            sp.add_argument("--dry-run", action="store_true", help="show every change, make none")
            sp.add_argument("--models", action="store_true",
                            help="finish what setup could not download: the search models, then the service")
        elif name == "doctor":
            sp.add_argument("--json", action="store_true", help="the checks as JSON")
            sp.add_argument("--report", action="store_true", help="counts only, safe to paste into an issue")
            sp.add_argument("--licenses", action="store_true", help="the models' licenses")
        elif name == "uninstall":
            sp.add_argument("--keep-data", action="store_true", help="keep your memory")
            sp.add_argument("--yes", action="store_true",
                            help="no effect: deleting your memory is always asked")
        elif name == "export":
            sp.add_argument("--out", help="the file to write")
            sp.add_argument("--format", choices=("json", "md"), default="json")
            sp.add_argument("--include-claims", action="store_true")
        elif name == "import":
            sp.add_argument("file")
        elif name == "access":
            sp.add_argument("app", nargs="?", help="cursor, codex, ... (none: every app on this Mac)")
            sp.add_argument("level", nargs="?", help="everything, work or nothing (none: show it)")
        elif name == "update":
            sp.add_argument("--check", action="store_true", help="only say whether there is a newer version")
            sp.add_argument("--yes", action="store_true")
            sp.add_argument("--finish", metavar="FROM", help=argparse.SUPPRESS)
    return p


def utf8_everywhere():
    """Under a locale that is not UTF-8 (LANG=zh_CN.GB2312, ja_JP.SJIS, de_DE.ISO8859-1) Python reads and writes every
    file in that locale: config.toml with a name it cannot decode was a traceback in setup and doctor, and an app's
    settings file could be read garbled. Every file this program touches is UTF-8, so start again in Python's UTF-8
    mode (it cannot be turned on once Python runs), with what was typed on the command line passed on as UTF-8. Then
    only a Terminal is read and written in the locale's encoding, with ? for what it cannot show. The engine's own
    command does the same (lflabs_memory.cli.utf8_everywhere)."""
    try:
        enc = codecs.lookup(locale.getencoding()).name
    except LookupError:
        return
    if enc == "utf-8":
        return
    if not sys.flags.utf8_mode and "PYTHONUTF8" not in os.environ and len(sys.orig_argv) > 1:
        def arg(a):
            raw = os.fsencode(a)
            try:
                raw.decode("utf-8")
                return raw
            except UnicodeDecodeError:
                return raw.decode(enc, "replace").encode("utf-8")
        os.environ["PYTHONUTF8"] = "1"
        os.execv(sys.executable, [sys.executable, *(arg(a) for a in sys.orig_argv[1:])])
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if stream is not None and stream.isatty():
            stream.reconfigure(encoding=enc, errors="replace")


def main(argv=None):
    if argv is None:  # the command itself, not a test's call
        utf8_everywhere()
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] in FRONT:
        return front_door(argv)
    args = parser().parse_args(argv)
    try:
        return COMMANDS[args.command][0](args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
