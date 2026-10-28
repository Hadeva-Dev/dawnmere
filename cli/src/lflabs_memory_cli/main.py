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
    """The full sunrise plays on the first setup (no install.json yet) or with --show; a re-run gets the short one."""
    return show or not (data_dir() / "install.json").exists()


def play(setup, intro=True, plain=False, animate=True):
    """Run a setup behind the screen. Returns its exit code."""
    state = screen.ScreenState(steps=setup.plan(), expect_apps=setup.expect_apps, intro=intro,
                               **screen.detect(plain=plain, animate=animate))
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
    print(f"{COMMAND} setup is not built yet. To watch the setup screen: {COMMAND} setup --demo")
    return 2


def cmd_doctor(args):
    from . import doctor
    return doctor.main(as_json=args.json, as_report=args.report, licenses=args.licenses)


def cmd_uninstall(args):
    from . import uninstall
    return uninstall.main(keep_data=args.keep_data, yes=args.yes)


def cmd_export(args):
    from . import export
    return export.export(args.out, args.format, args.include_claims)


def cmd_import(args):
    from . import export
    return export.import_file(args.file)


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
    "update": (cmd_update, f"update {PRODUCT}"),
}


def parser():
    p = argparse.ArgumentParser(prog=COMMAND, description=f"{PRODUCT}: one memory for every AI app you use.")
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
        elif name == "doctor":
            sp.add_argument("--json", action="store_true", help="the checks as JSON")
            sp.add_argument("--report", action="store_true", help="counts only, safe to paste into an issue")
            sp.add_argument("--licenses", action="store_true", help="the models' licenses")
        elif name == "uninstall":
            sp.add_argument("--keep-data", action="store_true", help="keep your memory")
            sp.add_argument("--yes", action="store_true", help="answer yes to every question")
        elif name == "export":
            sp.add_argument("--out", help="the file to write")
            sp.add_argument("--format", choices=("json", "md"), default="json")
            sp.add_argument("--include-claims", action="store_true")
        elif name == "import":
            sp.add_argument("file")
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
