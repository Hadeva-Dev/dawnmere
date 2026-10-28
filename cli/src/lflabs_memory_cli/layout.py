"""Where everything an install touches lives: neutral names only (spec 1, 4.1)."""
import os
import shutil
import sys
from pathlib import Path

SERVER = "lflabs-memory"                 # our MCP entry in every app's config, and the Claude Code plugin's name
ENGINE = "lflabs-memory"                 # the engine's console script
CONNECTOR = "lflabs-memory-connector"    # the npm package apps run to reach the engine
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


def short(path):
    """A path as the user reads it: ~ for the home folder."""
    s, h = str(path), str(home())
    return "~" + s[len(h):] if s == h or s.startswith(h + "/") else s
