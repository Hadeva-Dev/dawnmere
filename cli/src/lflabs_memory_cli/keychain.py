"""The Anthropic API key, kept in the login Keychain only (spec 5.4): never in config, logs, backups or argv."""
from .layout import KEYCHAIN
from .run import run


def store(key):
    """Save the key. `security -i` reads the command from stdin, so the key never appears in any process's argv."""
    service, account = KEYCHAIN
    line = f'add-generic-password -U -s "{service}" -a "{account}" -w "{key}"\n'
    if any(c in key for c in '"\\\n') or not key.strip():
        return False
    return run(["security", "-i"], input=line, timeout=20).ok


def present():
    service, account = KEYCHAIN
    return run(["security", "find-generic-password", "-s", service, "-a", account], timeout=10).ok


def delete():
    """Remove the key. True when one was removed; "not found" is fine."""
    service, account = KEYCHAIN
    return run(["security", "delete-generic-password", "-s", service, "-a", account], timeout=10).ok
