"""Which model reads transcripts in the background (spec 5.4), as setup asks and doctor reports it.

The engine's own llm.status() decides once setup has run; until then (and as a fallback) this does the same
checks: the claude version against MIN_CLAUDE, and a one-token ping that also tells whether it is logged in.
"""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from . import layout
from .layout import MIN_CLAUDE
from .run import run

MODELS = {"haiku": "Haiku", "sonnet": "Sonnet"}
API_MODELS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5"}
NONE_LOSES = "recall and remember work; automatic saving, claims, handoffs and translation are off"
# claude -p with nothing of the user's loaded: no hooks (ours would recall into the ping), no MCP, no tools
QUIET = ["--no-session-persistence", "--strict-mcp-config", "--tools", "", "--setting-sources", "",
         "--disable-slash-commands"]


# What points Claude Code at another endpoint or provider (the engine's llm.routed, kept the same): never passed to our
# own claude runs, so a ping says whether the user's Claude plan works, not another provider's endpoint.
ROUTING_PREFIXES = ("ANTHROPIC_", "VERTEX_REGION_CLAUDE_")
ROUTING_VARS = {"CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
                "CLAUDE_CODE_SKIP_BEDROCK_AUTH", "CLAUDE_CODE_SKIP_VERTEX_AUTH", "CLAUDE_CODE_SKIP_FOUNDRY_AUTH",
                "AWS_BEARER_TOKEN_BEDROCK", "CLOUD_ML_REGION"}
ENDPOINT_NOTE = "Claude Code is set to use {host}: background reading needs a Claude login for now"


def plain_env(env=None):
    """This environment less what reroutes Claude Code (ROUTING_PREFIXES, ROUTING_VARS)."""
    return {k: v for k, v in (os.environ if env is None else env).items()
            if not (k.startswith(ROUTING_PREFIXES) or k in ROUTING_VARS)}


def claude_endpoint(env=None, settings_files=None):
    """The host Claude Code is set to use instead of Anthropic: ANTHROPIC_BASE_URL in Claude Code's settings.json "env"
    (~/.claude, or CLAUDE_CONFIG_DIR's), which Claude Code applies over the shell's, else in this environment; None
    when it is Anthropic's own or unset, or a file cannot be read. The host only, never a path, token or key."""
    env = os.environ if env is None else env
    if settings_files is None:
        settings_files = [layout.home() / ".claude" / "settings.json"]
        if env.get("CLAUDE_CONFIG_DIR"):
            settings_files.insert(0, os.path.join(os.path.expanduser(env["CLAUDE_CONFIG_DIR"]), "settings.json"))
    urls = []
    for f in settings_files:
        try:
            data = json.loads(open(f, encoding="utf-8").read())
        except (OSError, ValueError):
            continue  # missing or malformed: it says nothing
        if isinstance(data, dict) and isinstance(data.get("env"), dict):
            urls.append(data["env"].get("ANTHROPIC_BASE_URL"))
    urls.append(env.get("ANTHROPIC_BASE_URL"))
    for url in urls:
        if not isinstance(url, str) or not url.strip():
            continue
        url = url.strip()
        try:
            host = urllib.parse.urlsplit(url if "//" in url else "//" + url).hostname
        except ValueError:
            continue
        if host and host != "api.anthropic.com":
            return host
    return None


MIN_CODEX = (0, 160, 0)  # the engine's llm.MIN_CODEX
# OpenAI-compatible providers the engine knows (llm.PROVIDERS has their addresses and models): the names setup shows
PROVIDERS = {"openai": "OpenAI", "gemini": "Google Gemini", "deepseek": "DeepSeek", "kimi": "Kimi (Moonshot)",
             "kimi-cn": "Kimi (Moonshot, moonshot.cn)", "qwen": "Qwen (Alibaba)",
             "qwen-intl": "Qwen (Alibaba, international)", "glm": "GLM (Zhipu)", "zai": "GLM (Z.ai)",
             "doubao": "Doubao (Volcengine)", "siliconflow": "SiliconFlow", "openrouter": "OpenRouter",
             "ollama": "Ollama on this Mac"}
NEEDS_MODEL = ("doubao", "siliconflow", "openrouter", "ollama")  # no model of their own in llm.PROVIDERS: ask for one
OTHER = "openai-compatible"  # the Keychain name of a key for an address the user typed (llm.OpenAICompat.account)


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
            timeout=90, env=plain_env())  # the user's Claude plan, never an endpoint Claude Code was pointed at
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


def engine_backends():
    """The backends the installed engine has (llm.BACKENDS), so setup never offers one it cannot run."""
    try:
        from lflabs_memory import llm
        return set(llm.BACKENDS)
    except Exception:
        return {"claude-cli", "anthropic-api", "none"}


def codex_status():
    """Whether the user's ChatGPT plan can read for memory, through Codex: installed, new enough, logged in."""
    r = run(["codex", "--version"], timeout=20)
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", r.out) if r.ok else None
    if not m:
        return Status("codex-cli", False, note="Codex not found")
    text = m.group(0)
    if tuple(int(x) for x in m.groups()) < MIN_CODEX:
        return Status("codex-cli", False, text, note=f"Codex {text} is older than {'.'.join(map(str, MIN_CODEX))}")
    said = run(["codex", "login", "status"], timeout=20)
    said = (said.out + said.err).lower()
    logged = False if "not logged in" in said else True if "logged in" in said else None
    return Status("codex-cli", logged is not False, text, logged,
                  "" if logged is not False else "Codex is not logged in: run codex login", usable=True)


def provider_ping(provider, key, api_base=None, model=None):
    """(ok, note): one tiny call to an OpenAI-compatible provider with this key, through the engine's own backend
    class so setup and the service ask the same way. Nothing is written: the key is handed to it in memory."""
    try:
        from dataclasses import replace
        from lflabs_memory import config, llm
        b = llm.OpenAICompat()
    except Exception:
        return False, "this version of the engine cannot use that provider"
    b._key = key or ""
    cfg = config.peek() if hasattr(config, "peek") else config.current()
    patched = replace(cfg, llm=replace(cfg.llm, backend="openai-api", provider=provider or "", api_base=api_base or "",
                                       **({"main_model": model, "cheap_model": model} if model else {})))
    old = config.CFG if hasattr(config, "CFG") else None
    try:
        config.CFG = patched
        b.json("Say ok.", {"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}},
               "Answer ok true.", model=patched.llm.cheap_model, timeout=60)
        return True, ""
    except Exception as e:  # llm.Unavailable, RuntimeError: its own words, which never hold the key
        return False, str(e)[:200]
    finally:
        config.CFG = old


# The coding tools whose own sign-in can read for memory (the engine's plan backends), in the order setup offers them:
# backend -> (command, name, what setup calls it)
PLANS = {"codex-cli": ("codex", "Codex", "your ChatGPT plan, through Codex"),
         "kimi-cli": ("kimi", "Kimi Code", "your Kimi plan, through Kimi Code"),
         "qwen-cli": ("qwen", "Qwen Code", "your Qwen plan, through Qwen Code"),
         "gemini-cli": ("gemini", "Gemini CLI", "your Google sign-in, through Gemini CLI")}


def plan_status(name, path=None):
    """Whether this tool's sign-in can read for memory. Codex says so itself (`codex login status`); the others have
    no such command, so the engine's own backend makes one tiny call through them. ok: installed, new enough and
    signed in."""
    if name == "codex-cli":
        return codex_status()
    try:
        from dataclasses import replace
        from lflabs_memory import config, llm
        cmd = PLANS[name][0]
        cfg = config.peek() if hasattr(config, "peek") else config.current()
        old = config.CFG
        config.CFG = replace(cfg, llm=replace(cfg.llm, backend=name, **({f"{cmd}_path": path} if path else {})))
        try:
            s = llm.BACKENDS[name]().status(ping=True)
        finally:
            config.CFG = old
        return Status(name, bool(s.ok), s.version, s.logged_in, s.note or "", usable=bool(s.version) and (
            s.ok or s.logged_in is False))
    except Exception as e:
        return Status(name, False, note=str(e)[:200])
