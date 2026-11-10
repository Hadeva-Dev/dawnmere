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
    """Write the plist and (re)load it. Returns the commands run as [(argv, ok, note)]: note is launchctl's first
    line of error text when it failed, else ""."""
    logs_dir().mkdir(parents=True, exist_ok=True)
    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(engine_bin))
    os.chmod(path, 0o644)
    done = []
    if loaded()[0]:  # a previous install's agent: replace it
        argv = ["launchctl", "bootout", f"{domain()}/{LABEL}"]
        done.append(_ran(argv))
        # bootout returns before the old daemon has exited, and until it has, launchd answers a bootstrap of
        # the same label with "Bootstrap failed: 5: Input/output error" (seen on macOS 26, 2026-11-08).
        wait_gone()
    argv = ["launchctl", "bootstrap", domain(), str(path)]
    done.append(_ran(argv))
    return done


def restart():
    """Unload the agent, wait for it to leave, load it again: [(argv, ok, note)] as install's."""
    done = [_ran(["launchctl", "bootout", f"{domain()}/{LABEL}"])]
    wait_gone()
    done.append(_ran(["launchctl", "bootstrap", domain(), str(plist_path())]))
    return done


def _ran(argv):
    r = run(argv, timeout=30)
    lines = r.err.strip().splitlines()
    return argv, r.ok, ("" if r.ok else lines[0] if lines else f"launchctl exited {r.code}")


def wait_gone(timeout=15.0, step=0.25):
    """Whether the agent has left the domain within timeout seconds (after a bootout)."""
    end = time.monotonic() + timeout
    while loaded()[0]:
        if time.monotonic() >= end:
            return False
        time.sleep(step)
    return True


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
        wait_gone()  # bootout returns before the daemon has exited (and let go of its sockets)
    path = plist_path()
    had = path.exists()
    path.unlink(missing_ok=True)
    if was or had:
        return True, "stopped and removed"
    return False, "already gone"
