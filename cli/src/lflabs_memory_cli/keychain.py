"""The Anthropic API key, kept in the login Keychain only (spec 5.4): never in config, logs, backups or argv."""
from .layout import KEYCHAIN
from .run import run


def account(provider=None):
    """The Keychain account of a key: Anthropic's, or "<provider>-api-key" for an OpenAI-compatible provider (the
    engine looks under the same name: llm.OpenAICompat.account)."""
    return f"{provider}-api-key" if provider else KEYCHAIN[1]


def store(key, provider=None):
    """Save the key. `security -i` reads the command from stdin, so the key never appears in any process's argv."""
    service, account = KEYCHAIN[0], globals()["account"](provider)
    line = f'add-generic-password -U -s "{service}" -a "{account}" -w "{key}"\n'
    if any(c in key for c in '"\\\n') or not key.strip():
        return False
    return run(["security", "-i"], input=line, timeout=20).ok


def present(provider=None):
    service, account = KEYCHAIN[0], globals()["account"](provider)
    return run(["security", "find-generic-password", "-s", service, "-a", account], timeout=10).ok


def delete(provider=None):
    """Remove the key. True when one was removed; "not found" is fine."""
    service, account = KEYCHAIN[0], globals()["account"](provider)
    return run(["security", "delete-generic-password", "-s", service, "-a", account], timeout=10).ok


def delete_all(providers):
    """Remove Anthropic's key and every provider's. True when any was removed."""
    return any([delete()] + [delete(p) for p in providers])
