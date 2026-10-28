"""The background service: a LaunchAgent that runs `lflabs-memory daemon` (spec 10.3)."""
import os
import re
import time
from importlib import resources
from xml.sax.saxutils import escape

from . import sockets
from .layout import LABEL, data_dir, home, logs_dir, plist_path
from .run import run


def render(engine_bin, h=None, data=None):
    """The plist text, every {{...}} filled with XML escaping."""
    text = (resources.files(__package__) / "com.lflabs.memory.plist.in").read_text()
    values = {"ENGINE_BIN": str(engine_bin), "HOME": str(h or home()), "DATA_DIR": str(data or data_dir())}
    return re.sub(r"\{\{(\w+)\}\}", lambda m: escape(values[m.group(1)]), text)


def domain():
    return f"gui/{os.getuid()}"


def loaded():
    """(loaded, pid or None) from launchctl print."""
    r = run(["launchctl", "print", f"{domain()}/{LABEL}"], timeout=10)
    if not r.ok:
        return False, None
    m = re.search(r"^\s*pid = (\d+)", r.out, re.M)
    return True, int(m.group(1)) if m else None


def install(engine_bin):
    """Write the plist and (re)load it. Returns the commands run as [(argv, ok)]."""
    logs_dir().mkdir(parents=True, exist_ok=True)
    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(engine_bin))
    os.chmod(path, 0o644)
    done = []
    if loaded()[0]:  # a previous install's agent: replace it
        argv = ["launchctl", "bootout", f"{domain()}/{LABEL}"]
        done.append((argv, run(argv, timeout=30).ok))
    argv = ["launchctl", "bootstrap", domain(), str(path)]
    done.append((argv, run(argv, timeout=30).ok))
    return done


def wait_ready(timeout=20.0, step=0.25):
    """Whether the engine's socket and the connector socket both answer within timeout seconds."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if sockets.alive(sockets.engine_path()) and sockets.ping_connector():
            return True
        time.sleep(step)
    return False


def remove():
    """Unload and delete the agent. (what happened, as one note) for uninstall's report."""
    was, _ = loaded()
    if was:
        run(["launchctl", "bootout", f"{domain()}/{LABEL}"], timeout=30)
    path = plist_path()
    had = path.exists()
    path.unlink(missing_ok=True)
    if was or had:
        return True, "stopped and removed"
    return False, "already gone"
