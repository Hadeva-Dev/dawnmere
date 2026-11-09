"""Where everything an install touches lives: neutral names only (spec 1, 4.1)."""
import os
import shutil
import sys
from pathlib import Path

from .brand import COMMAND, REPO
from .run import run

SERVER = "lflabs-memory"                 # our MCP entry in every app's config, and the Claude Code plugin's name
ENGINE = "lflabs-memory"                 # the engine's console script
CONNECTOR = f"{COMMAND}-connector"       # the npm package apps run to reach the engine: the one branded identifier
CONNECTOR_VERSION = "0.1.1"
CLIENT_ENV = "LFLABS_MEMORY_CLIENT"
MARKETPLACE = "lflabs"                   # .claude-plugin/marketplace.json's name
REPO_DIR = REPO.replace("/", "-")        # the folder Claude Code clones the marketplace's repo into
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


def lf_labs_dir():
    """The folder above the data folder, which also holds the connector's socket: owner only, like the data folder."""
    return home() / "Library/Application Support/LF Labs"


def data_dir():
    return Path(os.environ[HOME_ENV]).expanduser() if os.environ.get(HOME_ENV) else lf_labs_dir() / "Memory"


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
        lf_labs_dir() / "memory-connector.sock"


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
    interactive, so ~/.zprofile and ~/.zshrc are both read. install.sh and doctor check it the same way; install.sh
    puts the line in ~/.zprofile, and the advice below names it too."""
    return run(["zsh", "-lic", f"command -v {COMMAND}"], timeout=15).ok


_GIT = []


def git_available(which=None, link="/var/db/xcode_select_link"):
    """Whether git really runs, decided without running git or xcrun: on a Mac without the Command Line Tools,
    /usr/bin/git is Apple's stub, and running it puts up a dialog offering to install them. Another git (Homebrew's)
    is real; /usr/bin/git is when the active developer folder (DEVELOPER_DIR, else xcode-select's link, else
    /Library/Developer/CommandLineTools) has usr/bin/git. Asked once per process (the engine's mem.git_available is
    the same test)."""
    if _GIT:
        return _GIT[0]
    found = (which or shutil.which)("git")
    if not found:
        ok = False
    elif os.path.realpath(found) != "/usr/bin/git":
        ok = True
    else:
        dev = os.environ.get("DEVELOPER_DIR")
        if not dev:
            try:
                dev = os.readlink(link)
            except OSError:
                dev = "/Library/Developer/CommandLineTools"
        ok = os.path.isfile(os.path.join(dev, "usr", "bin", "git"))
    _GIT.append(ok)
    return ok


XCODE_SELECT = "/usr/bin/xcode-select"  # a real program, not one of Apple's stubs: it never opens a dialog


def developer_tools():
    """Whether Apple's developer tools are there: xcode-select names a folder holding usr/bin/git (Xcode's or the
    Command Line Tools'). Without them, /usr/bin/git, install_name_tool and the like are stubs that open a dialog
    offering to install them."""
    r = run([XCODE_SELECT, "-p"], timeout=10)
    return r.ok and os.path.isfile(os.path.join(r.out.strip(), "usr", "bin", "git"))


def find_claude():
    """Claude Code's absolute path as a new Terminal window finds it (login and interactive zsh: its PATH, or the
    alias the old local installer made), else the claude on this PATH. The background service has launchd's fixed
    PATH, so setup stores this in config.toml ([llm] claude_path). None when there is none."""
    r = run(["zsh", "-lic", "whence -p claude || alias claude"], timeout=15)
    for line in reversed((r.out or "").splitlines() if r.ok else []):
        line = line.strip()
        if line.split("=", 1)[0] in ("claude", "alias claude"):
            line = line.split("=", 1)[1].strip().strip("'\"")
        p = os.path.expanduser(line)
        if os.path.isabs(p) and os.access(p, os.X_OK):
            return p
    found = shutil.which("claude")
    return str(Path(found).absolute()) if found else None


def path_line():
    return f'export PATH="{tool_bin()}:$PATH"'


def path_advice():
    """Word for word what install.sh prints."""
    return f"To run {COMMAND} later, add this line to ~/.zprofile:\n  {path_line()}"


def short(path):
    """A path as the user reads it: ~ for the home folder."""
    s, h = str(path), str(home())
    return "~" + s[len(h):] if s == h or s.startswith(h + "/") else s
