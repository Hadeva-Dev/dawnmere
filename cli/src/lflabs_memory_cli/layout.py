"""Where everything an install touches lives: neutral names only (spec 1, 4.1)."""
import os
import shutil
import sys
from pathlib import Path

from .brand import COMMAND
from .run import run

SERVER = "lflabs-memory"                 # our MCP entry in every app's config, and the Claude Code plugin's name
ENGINE = "lflabs-memory"                 # the engine's console script
CONNECTOR = f"{COMMAND}-connector"       # the npm package apps run to reach the engine: the one branded identifier
CONNECTOR_VERSION = "0.1.0"
CLIENT_ENV = "LFLABS_MEMORY_CLIENT"
MARKETPLACE = "lflabs"                   # .claude-plugin/marketplace.json's name
LABEL = "com.lflabs.memory"              # the LaunchAgent
KEYCHAIN = ("LF Labs Memory", "anthropic-api-key")   # (service, account)
BACKUP_TAG = "lflabs-backup"             # <file>.lflabs-backup-<UTC time>
CLI_DIST = "lflabs-memory-cli"
ENGINE_DIST = "lflabs-memory-engine"
MIN_CLAUDE = (2, 1, 301)
HOME_ENV = "LFLABS_MEMORY_HOME"
SOCKET_ENV = "LFLABS_MEMORY_SOCKET"


def home():
    return Path.home()


def data_dir():
    return Path(os.environ[HOME_ENV]).expanduser() if os.environ.get(HOME_ENV) else \
        home() / "Library/Application Support/LF Labs/Memory"


def install_json():
    return data_dir() / "install.json"


def engine_record():
    """The engine's absolute path, written by setup: what the Claude Code plugin's hooks run (plugin/scripts/engine)."""
    return data_dir() / "engine-path"


def logs_dir():
    return home() / "Library/Logs/LF Labs"


def engine_sock():
    return data_dir() / "engine.sock"


def connector_sock():
    return Path(os.environ[SOCKET_ENV]).expanduser() if os.environ.get(SOCKET_ENV) else \
        home() / "Library/Application Support/LF Labs/memory-connector.sock"


def plist_path():
    return home() / f"Library/LaunchAgents/{LABEL}.plist"


def engine_bin():
    """The engine's console script, absolute: the one on PATH (uv links it into ~/.local/bin), else the one beside this
    Python (the same tool environment). None when neither exists."""
    found = shutil.which(ENGINE)
    if found:
        return str(Path(found).absolute())
    sibling = Path(sys.executable).parent / ENGINE
    return str(sibling) if sibling.exists() else None


def uv_bin():
    """uv: the one on PATH, else the one install.sh puts in ~/.local/bin (often not on PATH yet). None when neither."""
    found = shutil.which("uv")
    if found:
        return found
    local = home() / ".local/bin/uv"
    return str(local) if os.access(local, os.X_OK) else None


def tool_bin():
    """The folder uv links the CLI's command into (uv tool dir --bin), as install.sh asks it."""
    r = run([uv_bin(), "tool", "dir", "--bin"], timeout=15) if uv_bin() else None
    return r.out.strip() if r and r.ok and r.out.strip() else str(home() / ".local/bin")


def on_shell_path():
    """Whether a new Terminal window finds the CLI's command: zsh started as Terminal starts it, login and
    interactive, so ~/.zprofile and ~/.zshrc are both read (the advice below names ~/.zshrc). install.sh and doctor
    check it the same way."""
    return run(["zsh", "-lic", f"command -v {COMMAND}"], timeout=15).ok


def path_line():
    return f'export PATH="{tool_bin()}:$PATH"'


def path_advice():
    """Word for word what install.sh prints."""
    return f"To run {COMMAND} later, add this line to ~/.zshrc:\n  {path_line()}"


def short(path):
    """A path as the user reads it: ~ for the home folder."""
    s, h = str(path), str(home())
    return "~" + s[len(h):] if s == h or s.startswith(h + "/") else s
