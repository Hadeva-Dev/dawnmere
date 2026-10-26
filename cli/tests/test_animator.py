"""The animator in a real (pseudo) terminal: key skip, Ctrl-C, plain output."""
import fcntl
import io
import os
import pty
import select
import signal
import struct
import subprocess
import sys
import termios
import threading
import time

from conftest import plan

from lflabs_memory_cli import screen
from lflabs_memory_cli.screen import Animator, ScreenState, frame, visible


class Capture(io.StringIO):
    def isatty(self):
        return True


def instant_setup(ui):
    for s in ui.state.steps:
        ui.step(s.label, "running")
        if s.apps:
            ui.apps([screen.AppResult("Claude Code", "plugin", status="ok"),
                     screen.AppResult("Cursor", "MCP", "restart Cursor", status="ok")])
        ui.step(s.label, "ok", "done")
    ui.memory("use pnpm, never npm")


def test_key_skips():
    """A key press mid-intro draws the final frame within one frame time."""
    out = Capture()
    keys_r, keys_w = os.pipe()
    state = ScreenState(steps=plan(), color=False, width=80, height=40, expect_apps=2)
    ui = Animator(state, out=out, keys=keys_r)
    ui.start()
    instant_setup(ui)
    with ui._lock:
        state.finished = ui._now()
    time.sleep(0.5)                       # mid-intro: the ring is drawn, the wordmark not yet
    assert state.skipped is None
    pressed = time.monotonic()
    os.write(keys_w, b"x")
    ui._thread.join(timeout=2)
    took = time.monotonic() - pressed
    assert not ui._thread.is_alive()
    assert took < 2 / ui.FPS + 0.05, took
    final = frame(screen.done_at(state), state)
    assert ui._prev[:len(final)] == final
    assert any("Dawnmere is on." in visible(x) for x in final)
    ui.finish()
    os.close(keys_r)
    os.close(keys_w)


def test_plain_output_streams_lines():
    out = Capture()
    state = ScreenState(steps=plan(), plain=True)
    ui = Animator(state, out=out)
    ui.start()
    ui.step("Claude Code", "running")
    assert out.getvalue() == ""
    ui.step("Claude Code", "ok", "found, logged in")
    assert out.getvalue() == "[ok] Claude Code: found, logged in\n"
    instant_setup(ui)
    ui.finish()
    text = out.getvalue()
    assert "\x1b" not in text and text.count("Dawnmere is on.") == 1


def spawn(*args, cols=80, rows=40, env=None):
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    child_env = {k: v for k, v in os.environ.items() if k not in ("NO_COLOR", "CI")}
    child_env.update({"LANG": "en_US.UTF-8", "TERM": "xterm-256color", **(env or {})})
    proc = subprocess.Popen([sys.executable, "-m", "lflabs_memory_cli.main", *args], stdin=slave, stdout=slave,
                            stderr=slave, env=child_env, start_new_session=True)
    os.close(slave)
    return proc, master


def read_for(fd, seconds):
    buf, deadline = b"", time.monotonic() + seconds
    while time.monotonic() < deadline:
        r, _, _ = select.select([fd], [], [], 0.05)
        if r:
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
    return buf


def test_cursor_restored_on_interrupt():
    proc, fd = spawn("setup", "--demo")
    before = read_for(fd, 1.0)
    assert screen.HIDE.encode() in before, "the cursor is hidden while it animates"
    proc.send_signal(signal.SIGINT)
    after = read_for(fd, 2.0)
    os.close(fd)
    assert proc.wait(5) == 130
    assert screen.SHOW.encode() in after, "the cursor is shown again"
    assert after.rindex(screen.SHOW.encode()) > after.rfind(screen.HIDE.encode())
    assert b"\x1b[2K" in after, "the line is cleared"
    assert b"Traceback" not in after


def test_full_demo_in_a_terminal():
    proc, fd = spawn("setup", "--demo")
    out = read_for(fd, 15.0)
    os.close(fd)
    assert proc.wait(5) == 0
    text = out.decode()
    assert "Dawnmere is on." in text and text.rstrip().endswith(screen.SHOW)
