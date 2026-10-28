"""Questions on the terminal. With --yes, or when nobody can answer (no terminal), the default stands."""
import getpass
import sys


def yes_no(question, default, assume=None):
    """True or False. assume: the answer --yes gives (None: ask)."""
    if assume is not None:
        return assume
    if not sys.stdin.isatty():
        return default
    hint = "[Y/n]" if default else "[y/N]"
    try:
        got = input(f"{question} {hint} ").strip().lower()
    except EOFError:
        return default
    return default if not got else got.startswith("y")


def text(question, default=""):
    if not sys.stdin.isatty():
        return default
    try:
        got = input(f"{question} [{default}] " if default else f"{question} ").strip()
    except EOFError:
        return default
    return got or default


def secret(question):
    """A hidden answer (an API key): never echoed, never logged."""
    if not sys.stdin.isatty():
        return ""
    try:
        return getpass.getpass(f"{question} ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""
