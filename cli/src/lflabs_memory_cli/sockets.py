"""Talking to the engine: its hook socket (engine.sock) and the connector socket (lflabs-memory/1, PROTOCOL.md)."""
import json
import os
import socket
import stat

from .layout import connector_sock, engine_sock

PROTOCOL = "lflabs-memory/1"


def engine_path():
    return engine_sock()


def alive(path, timeout=1.0):
    """Whether something accepts connections on this Unix socket."""
    try:
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(timeout)
            s.connect(str(path))
        return True
    except OSError:
        return False


def _owned(path):
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISSOCK(st.st_mode) and st.st_uid == os.getuid()


def ask(tool, args=None, client=None, timeout=15.0, path=None):
    """One lflabs-memory/1 request: the reply dict, or {"ok": False, "error": ...} when nothing (or not ours) answers."""
    path = path or connector_sock()
    if not _owned(path):
        return {"ok": False, "error": "nothing is listening"}
    req = {"protocol": PROTOCOL, "tool": tool, "args": args or {},
           "client": {"name": client, "key": None, "hint": None, "connector": None}}
    try:
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(timeout)
            s.connect(str(path))
            s.sendall((json.dumps(req) + "\n").encode())
            line = s.makefile("rb").readline(1 << 20)
        reply = json.loads(line)
        return reply if isinstance(reply, dict) else {"ok": False, "error": "a reply that is not an object"}
    except (OSError, ValueError) as e:
        return {"ok": False, "error": f"no answer ({type(e).__name__})"}


def ping_connector(path=None):
    """The engine's name and version when an engine answers on the connector socket, else None."""
    r = ask("ping", timeout=2.0, path=path)
    return r.get("text") if r.get("ok") else None
