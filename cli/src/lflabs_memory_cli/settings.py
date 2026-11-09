"""DATA_DIR/config.toml as setup writes it (spec 5.2) and doctor reads it."""
import json
import os
import tomllib

from .layout import data_dir

DEFAULTS = {"llm": {"backend": "claude-cli", "main_model": "haiku", "cheap_model": "haiku", "daily_calls": 200},
            "privacy": {"codex_sessions": False, "chat_index": False, "holdout": False, "new_clients": "work"},
            "connector": {"enabled": True}}


def path():
    return data_dir() / "config.toml"


def load():
    """config.toml merged over the defaults ({} sections when there is no file)."""
    try:
        raw = tomllib.loads(path().read_text())
    except (OSError, tomllib.TOMLDecodeError):
        raw = {}
    out = {k: v for k, v in raw.items() if not isinstance(v, dict)}
    for section, values in DEFAULTS.items():
        got = raw.get(section) if isinstance(raw.get(section), dict) else {}
        out[section] = {**values, **got}
    return out


def _value(v):
    return ("true" if v else "false") if isinstance(v, bool) else str(v) if isinstance(v, int) else json.dumps(v)


def render(owner_name, backend, main_model="haiku", codex_sessions=False, claude_path=None):
    cfg = json.loads(json.dumps(DEFAULTS))
    cfg["llm"].update(backend=backend, main_model=main_model, **({"claude_path": claude_path} if claude_path else {}))
    cfg["privacy"]["codex_sessions"] = codex_sessions
    lines = ["version = 1", 'profile = "generic"'] + ([f"owner_name = {_value(owner_name)}"] if owner_name else [])
    for section, values in cfg.items():
        lines += ["", f"[{section}]"] + [f"{k} = {_value(v)}" for k, v in values.items()]
    return "\n".join(lines) + "\n"


def save(text):
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = p.with_name(p.name + ".tmp")
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        f.write(text)
    os.replace(tmp, p)
