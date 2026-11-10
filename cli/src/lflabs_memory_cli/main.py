"""The command line: setup, doctor, uninstall, export, update."""
import argparse
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
    "access": (cmd_access, "change what an AI app may see: access cursor everything|work"),
    "update": (cmd_update, f"update {PRODUCT}"),
}


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
            sp.add_argument("--only", help="apps to connect: claude-code,codex,cursor,windsurf,gemini,copilot")
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
            sp.add_argument("app", help="cursor, codex, ...")
            sp.add_argument("level", nargs="?", help="everything, nothing-personal, work or nothing (none: show it)")
        elif name == "update":
            sp.add_argument("--check", action="store_true", help="only say whether there is a newer version")
            sp.add_argument("--yes", action="store_true")
            sp.add_argument("--finish", metavar="FROM", help=argparse.SUPPRESS)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        return COMMANDS[args.command][0](args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
