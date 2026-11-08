"""Draw a whole run through a terminal emulator (pyte) and read the screen back: what a user would see."""
import io

import pyte
import pytest
from conftest import plan

from lflabs_memory_cli import screen
from lflabs_memory_cli.screen import Animator, ScreenState, frame, visible


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def play_through(cols, rows):
    """Every frame of an instant setup, drawn through Animator._draw into a cols x rows emulator."""
    term = pyte.Screen(cols, rows)
    stream = pyte.Stream(term)
    out = io.StringIO()
    clock = Clock()
    state = ScreenState(steps=plan(), color=True, width=cols, height=rows, expect_apps=3)
    ui = Animator(state, out=out, clock=clock)
    ui._t0 = 0.0
    for s in state.steps:
        ui.step(s.label, "running")
        if s.apps:
            apps = []
            for name in ("Claude Code", "Codex", "Cursor"):
                apps.append(screen.AppResult(name, "MCP", status="ok"))
                ui.apps(apps)
        ui.step(s.label, "ok", "done")
    ui.memory("use pnpm, never npm")
    state.finished = 0.0
    for i in range(int(screen.done_at(state) * 30) + 2):
        clock.t = i / 30
        ui._draw(frame(clock.t, state))
        stream.feed(out.getvalue())
        out.seek(0)
        out.truncate()
    return [line.rstrip() for line in term.display], [visible(x) for x in frame(clock.t, state)]


@pytest.mark.parametrize("cols,rows", [(100, 46), (120, 40), (80, 35), (80, 34), (80, 24), (80, 14), (64, 20)])
def test_screen_shows_the_final_frame(cols, rows):
    shown, final = play_through(cols, rows)
    while shown and shown[-1] == "":
        shown.pop()
    k = min(len(shown), len(final))
    assert shown[-k:] == final[-k:], "the visible rows are the final frame's, with nothing garbled"
    if len(final) < rows:
        assert shown == final, "the whole screen is the final frame: no ghost copies of Kip above it"
    expect = "full" if rows >= 35 and cols >= 70 else "compact"
    assert screen._header(ScreenState(steps=plan(), width=cols, height=rows, expect_apps=3)) == expect


@pytest.mark.parametrize("rows,golden", [(40, "final"), (30, "compact-final")])
def test_no_ghosting(rows, golden):
    """The demo in a real pseudo-terminal, 100 columns wide, read back through pyte: the screen it ends on is the
    golden final frame (full at 40 rows, compact at 30), with no ghost copies of Kip and the cursor shown."""
    import os
    from pathlib import Path

    from test_animator import read_for, spawn
    proc, fd = spawn("setup", "--demo", cols=100, rows=rows, env={"COLUMNS": "100", "LINES": str(rows)})
    term = pyte.Screen(100, rows)
    stream = pyte.ByteStream(term)
    stream.feed(read_for(fd, 15.0))
    os.close(fd)
    assert proc.wait(5) == 0
    shown = [line.rstrip() for line in term.display]
    while shown and shown[-1] == "":
        shown.pop()
    want = [visible(x) for x in (Path(__file__).parent / "banner" / f"{golden}.txt").read_text().splitlines()]
    assert shown == want
    assert not term.cursor.hidden
