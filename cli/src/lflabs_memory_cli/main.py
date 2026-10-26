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


def not_yet(args):
    print(f"{COMMAND} {args.command} is not built yet.")
    return 2


COMMANDS = {
    "setup": (cmd_setup, "connect your AI apps to one memory on this Mac"),
    "doctor": (not_yet, "check that everything works"),
    "uninstall": (not_yet, "remove everything setup added"),
    "export": (not_yet, "save your memory to a file"),
    "update": (not_yet, f"update {PRODUCT}"),
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
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        return COMMANDS[args.command][0](args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
