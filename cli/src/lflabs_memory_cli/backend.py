"""Which model reads transcripts in the background (spec 5.4), as setup asks and doctor reports it.

The engine's own llm.status() decides once setup has run; until then (and as a fallback) this does the same
checks: the claude version against MIN_CLAUDE, and a one-token ping that also tells whether it is logged in.
"""
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from .layout import MIN_CLAUDE
from .run import run

MODELS = {"haiku": "Haiku", "sonnet": "Sonnet"}
API_MODELS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5"}
NONE_LOSES = "recall and remember work; automatic saving, claims, handoffs and translation are off"
# claude -p with nothing of the user's loaded: no hooks (ours would recall into the ping), no MCP, no tools
QUIET = ["--no-session-persistence", "--strict-mcp-config", "--tools", "", "--setting-sources", "",
         "--disable-slash-commands"]


@dataclass
class Status:
    name: str
    ok: bool
    version: str | None = None
    logged_in: bool | None = None
    note: str = ""
    usable: bool = False   # Claude Code installed and new enough, logged in or not: the plan can be the backend


def engine_status(ping=False):
    """The engine's own status (lflabs_memory.llm.status), once setup has written config.toml: None before that
    (loading the engine's config would create its data folder) or when the engine cannot say."""
    from . import settings
    if not settings.path().exists():
        return None
    try:
        from lflabs_memory import llm
        s = llm.status(ping=ping)
        return Status(s.name, bool(s.ok), getattr(s, "version", None), getattr(s, "logged_in", None),
                      getattr(s, "note", "") or "")
    except Exception:
        return None


def claude_version():
    """(version tuple, text) from `claude --version`, or (None, why)."""
    r = run(["claude", "--version"], timeout=20)
    if not r.ok:
        return None, "Claude Code not found" if r.code == 127 else "claude --version failed"
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", r.out)
    if not m:
        return None, "could not read the Claude Code version"
    return tuple(int(x) for x in m.groups()), m.group(0)


def claude_ping(model="haiku"):
    """(logged in, note): one tiny call through the user's own plan."""
    r = run(["claude", "-p", "--model", model, *QUIET, "--output-format", "json", "Reply with the word ok."],
            timeout=90)
    text = (r.out + r.err).lower()
    if "/login" in text or "not logged in" in text or "invalid api key" in text:
        return False, "Claude Code is not logged in: run claude, then /login"
    if "usage limit" in text or "rate limit" in text:
        return True, "Claude Code is logged in but at its usage limit right now"
    if not r.ok:
        return None, "claude -p did not answer"
    try:
        if json.loads(r.out).get("is_error"):
            return None, "claude -p answered with an error"
    except ValueError:
        pass
    return True, ""


def claude_status(model="haiku", ping=True):
    v, text = claude_version()
    if v is None:
        return Status("claude-cli", False, note=text)
    floor = ".".join(map(str, MIN_CLAUDE))
    if v < MIN_CLAUDE:
        return Status("claude-cli", False, text, note=f"Claude Code {text} is older than {floor}: update it "
                      "(claude update)")
    if not ping:
        return Status("claude-cli", True, text, usable=True)
    logged, note = claude_ping(model)
    return Status("claude-cli", bool(logged), text, logged, note, usable=True)


def api_ping(key, model="haiku"):
    """(ok, note): a one-token Messages API call with this key."""
    body = json.dumps({"model": API_MODELS[model], "max_tokens": 1,
                       "messages": [{"role": "user", "content": "ok"}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, method="POST", headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status == 200, ""
    except urllib.error.HTTPError as e:
        return False, "the key was refused" if e.code in (401, 403) else f"the API answered {e.code}"
    except (urllib.error.URLError, OSError):
        return False, "could not reach api.anthropic.com"
