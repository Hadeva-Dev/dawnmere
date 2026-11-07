"""The setup screen's frames (spec 9.1, Tests)."""
import os
from pathlib import Path

import pytest
from conftest import THREE, plan, scripted

from lflabs_memory_cli import screen
from lflabs_memory_cli.screen import (LABEL, AppResult, Memory, ScreenState, done_at, frame, pick_memory,
                                      self_check_row, sun_offset, track, visible)

GOLDEN = Path(__file__).parent / "banner"
UPDATE = bool(os.environ.get("UPDATE_GOLDEN"))
TRY_PREFIX = "Try it:"


def check_golden(name, lines):
    path = GOLDEN / f"{name}.txt"
    text = "\n".join(lines) + "\n"
    if UPDATE or not path.exists():
        path.write_text(text)
    assert text == path.read_text(), f"{name} differs from {path} (UPDATE_GOLDEN=1 to accept)"


def test_frames_golden():
    state = scripted()
    end = done_at(state)
    for name, t in [("t0.4", 0.4), ("t1.0", 1.0), ("t2.0", 2.0), ("mid-download", 3.1), ("final", end)]:
        check_golden(name, frame(t, state))
    check_golden("final-colour", [line.replace("\x1b", "\\e") for line in frame(end, scripted(color=True))])


def test_mid_download_shows_the_bar():
    row = next(visible(x) for x in frame(3.1, scripted()) if "Search models" in x)
    assert "─" * 20 in row and row.rstrip().endswith("MB")


def body_lines(state, t):
    return [visible(x) for x in frame(t, state)]


def times(state):
    end = done_at(state)
    return [i / 20 for i in range(int(end * 20) + 2)]


def test_width():
    """No line is wider than 68 columns, except the "Try it" line, which is one line only where the terminal fits it."""
    for kw in ({}, {"color": True}, {"check": 2.1}, {"memory": None}, {"apps": THREE[:1]}):
        state = scripted(**kw)
        for t in times(state):
            for line in body_lines(state, t):
                limit = state.width - 1 if line.lstrip().startswith(TRY_PREFIX) else 68
                assert len(line) <= limit, (kw, t, line)
    narrow = scripted(width=72)
    assert all(len(x) <= 68 for x in body_lines(narrow, done_at(narrow)))


def test_sun_tracks_progress():
    state = scripted()
    end = done_at(state)
    offs = [sun_offset(state, t) for t in times(state)]
    assert offs[0] == pytest.approx(screen.SUN_START)
    assert all(b <= a + 1e-9 for a, b in zip(offs, offs[1:])), "the sun never sinks"
    last_step_end = state.finished
    for t, off in zip(times(state), offs):
        if t < last_step_end:
            assert off > 0, f"sun clear of the horizon at {t} before setup finished"
    assert sun_offset(state, end) == 0


def test_sun_waits_for_a_slow_step():
    state = scripted(until=3.0)          # the download is a third of the way
    off = sun_offset(state, 3.0)
    assert 0 < off < screen.SUN_START
    assert sun_offset(state, 30.0) == pytest.approx(sun_offset(state, 3.6), abs=0.5)


@pytest.mark.parametrize("n", [1, 2, 3, 4, 6])
def test_ending_apps(n):
    names = ["Claude Code", "Codex", "Cursor", "Windsurf", "VS Code", "Gemini CLI"][:n]
    state = scripted(apps=names)
    lines = body_lines(state, done_at(state))
    app_line = next(x for x in lines if "◉" in x)
    assert len(app_line) <= 68
    if n == 6:
        assert "◉ +3 more" in app_line and "Windsurf" not in app_line
    else:
        assert app_line.count("◉") == n
    nodes, wire = track(names)
    if n > 1:
        assert 3 <= wire <= 11
    tail = {1: "saved", 2: "is now in both"}.get(n, f"is now in all {n}")
    assert any(tail in x for x in lines)
    if n == 1:
        assert any("Add Cursor or Codex later: dawnmere setup" in x for x in lines)


def mem(text, kind="feedback", section="prefs", created=0.0, **kw):
    return Memory(text, kind, section, created, **kw)


def test_memory_pick():
    assert pick_memory([mem("staging is on port 6543", "project", "projects"), mem("use pnpm, never npm")]) \
        == "use pnpm, never npm"
    assert pick_memory([mem("call the vendor on 415-555-0134 first")]) == "call the vendor on [phone] first"
    assert pick_memory([mem("my doctor says no coffee after 2"), mem("pay the mortgage on the 1st"),
                        mem("deploy key lives in 1Password", secret=True),
                        mem("I live in Berkeley", "user", "personal"),
                        mem("prefers short replies", "feedback", "personal"),
                        mem("labelled private by the model", private=True)]) is None
    long = "always write the migration first, then the model, then the API, then the tests"
    got = pick_memory([mem(long)])
    assert len(got) <= 48 and got.endswith("…") and long.startswith(got[:-1].rstrip())
    assert long[len(got) - 1] == " ", "cut at a word boundary"
    assert pick_memory([]) is None
    # ties: the shortest, then the newest
    assert pick_memory([mem("rule number one here"), mem("short rule")]) == "short rule"
    assert pick_memory([mem("same length A", created=1), mem("same length B", created=2)]) == "same length B"


def test_no_memory_gives_the_empty_travel_line():
    state = scripted(memory=None)
    lines = body_lines(state, done_at(state))
    assert any("Anything you tell one of them now reaches the others." in x for x in lines)
    assert not any("“" in x for x in lines if "Try it" not in x)


def test_fallbacks(monkeypatch):
    class Out:
        encoding = "utf-8"

        def __init__(self, tty):
            self.tty = tty

        def isatty(self):
            return self.tty

    monkeypatch.setattr(screen, "reduce_motion", lambda: False)
    utf8 = {"LANG": "en_US.UTF-8", "TERM": "xterm-256color"}
    assert screen.detect(Out(False), utf8)["plain"]
    assert screen.detect(Out(True), {**utf8, "CI": "1"})["plain"]
    assert screen.detect(Out(True), {**utf8, "TERM": "dumb"})["plain"]
    assert screen.detect(Out(True), utf8, plain=True)["plain"]
    tty = screen.detect(Out(True), utf8)
    assert not tty["plain"] and tty["unicode"] and tty["motion"] and tty["color"]
    assert not screen.detect(Out(True), {**utf8, "NO_COLOR": "1"})["color"]
    assert not screen.detect(Out(True), {"LANG": "C", "TERM": "xterm"})["unicode"]
    monkeypatch.setattr(screen, "reduce_motion", lambda: True)
    assert not screen.detect(Out(True), utf8)["motion"]

    # plain: lines only, no escapes
    state = scripted(plain=True)
    lines = frame(done_at(state), state)
    assert lines[0] == "[ok] Claude Code: found, logged in" and "Dawnmere is on." in lines
    assert not any("\x1b" in x or "⠀" <= x[:1] <= "⣿" for x in lines)

    # non-UTF-8: the ASCII logo and the spaced name, all ASCII, no animation
    state = scripted(unicode=False, color=True)
    for t in (0.4, done_at(state)):
        lines = body_lines(state, t)
        assert all(x.isascii() for x in lines)
        assert "      .--''''''--." in "\n".join(lines) and "D A W N M E R E" in "\n".join(lines)

    # Reduce Motion: still frames, sun at its height after each finished step, the ending drawn at once
    still = scripted(motion=False)
    end = done_at(still)
    assert end == screen._timeline(still).end, "no 3 s finale: the end is drawn at once"
    assert frame(2.6, still) == frame(2.61, still), "nothing moves between steps"
    assert sun_offset(still, 3.0) == sun_offset(still, 3.9), "the sun moves only when a step finishes"
    final = body_lines(still, end)
    assert any("Dawnmere is on." in x for x in final) and not any("●" in x for x in final)
    assert any(x.strip().startswith("•") for x in body_lines(still, 3.0)), "a still mark, not a spinner"

    # under 70 columns: one centred spaced name, then the steps
    narrow = scripted(width=60)
    lines = body_lines(narrow, done_at(narrow))
    assert lines[0].strip() == "D A W N M E R E" and lines[1] == ""
    assert lines[2].startswith(" ✓ Claude Code")

    # fewer than 34 rows: no logo, the wordmark stays
    short = scripted(height=33)
    lines = body_lines(short, done_at(short))
    assert lines[0] == screen.WORDMARK[0].rstrip()


def test_self_check_row(final):
    assert self_check_row(0.34) == ("ok", "recall in 0.34 s")
    state, end = final(check=0.34)
    assert " ✓ Self-check      recall in 0.34 s" in body_lines(state, end)

    state, end = final(check=2.1)
    lines = body_lines(state, end)
    assert " ! Self-check      recall in 2.10 s (slow: dawnmere doctor)" in lines
    assert any("Dawnmere is on." in x for x in lines), "setup still finishes"
    coloured = frame(end, scripted(check=2.1, color=True))
    assert any(f"38;5;{screen.AMBER}m!" in x for x in coloured)

    state, end = final(fail=True)
    lines = body_lines(state, end)
    assert " ✗ Self-check      the memory service did not answer" in lines
    assert not any("Dawnmere is on." in x or "Try it" in x or "◉" in x for x in lines)
    off = sun_offset(state, end + 1)
    assert off > 0 and sun_offset(state, end + 5) == off, "the sun stops where it is"
    coloured = scripted(fail=True, color=True)
    for t in (end, end + 0.5):
        assert not any(f"38;5;{c}m" in x for x in frame(t, coloured) for c in screen.FLASH[1:]), "no flash"


def fake_fast_machine():
    """Every step takes 5 ms except the 57 MB download, which takes 1 s; no intro, to measure only the floors."""
    state = ScreenState(steps=plan(), color=False, intro=False)
    t = 0.0
    for s in state.steps:
        s.started, s.status = t, "running"
        if s.apps:
            for name in THREE:
                state.apps.append(AppResult(name, "MCP", status="ok", started=t, ended=t + 0.005))
                t += 0.005
        t += 1.0 if s.label == "Search models" else 0.005
        s.ended, s.status = t, "ok"
    state.finished = t
    return state


def test_step_floor():
    state = fake_fast_machine()
    tl = screen._timeline(state)
    for (start, end), s in zip(tl.steps, state.steps):
        assert end - start >= screen.FLOOR - 1e-9, s.label
    for start, end in tl.leaves:
        assert end - start >= screen.FLOOR - 1e-9
    added = tl.end - state.finished
    assert added < 2.5, added

    slow = ScreenState(steps=plan(), color=False, intro=False)
    s = slow.steps[0]
    s.started, s.ended, s.status = 0.0, 2.0, "ok"
    slow.finished = 2.0
    start, end = screen._timeline(slow).steps[0]
    assert end - start == pytest.approx(2.0), "a 2 s step is not lengthened"


def test_short_version_on_rerun(tmp_path, monkeypatch):
    from lflabs_memory_cli.main import full_show
    monkeypatch.setenv("LFLABS_MEMORY_HOME", str(tmp_path))
    assert full_show()
    (tmp_path / "install.json").write_text("{}")
    assert not full_show()
    assert full_show(show=True)
    state = scripted(intro=False, start=0.0)
    for t in times(state):
        lines = body_lines(state, t)
        assert not any("⣿" in x or "⠶" in x for x in lines), "no logo or wordmark"
        assert not any("◉" in x for x in lines)
    lines = body_lines(state, done_at(state))
    assert lines[0].startswith(" ✓ Claude Code") and lines[-1] == " Dawnmere is on."


def test_apps_arrive_one_at_a_time():
    state = scripted()
    tl = screen._timeline(state)
    starts = [ls for ls, _ in tl.leaves]
    for k in range(3):
        t = starts[k] + 0.01
        lines = body_lines(state, t)
        leaves = [x for x in lines if x.startswith("   ├") or x.startswith("   └")]
        assert len(leaves) == k + 1, (t, lines)
        assert all("Your apps" not in x or f"{k} of 3" in x for x in lines if "Your apps" in x)
        assert any(c in leaves[-1] for c in screen.SPIN), "the newest leaf spins"
        assert all(not any(c in x for c in screen.SPIN) for x in leaves[:-1]), "earlier leaves settled"
        for later in THREE[k + 1:]:
            assert not any(later in x for x in leaves), f"{later} appeared before its wiring started"
    assert any("1 of 3" in x for x in body_lines(state, starts[1] + 0.01))


def test_alignment(final):
    state, end = final()
    lines = body_lines(state, end)
    body = lines[lines.index(" ✓ Claude Code     found, logged in"):]
    result_col = 1 + 2 + LABEL
    for x in body:
        if x[1:2] and x[1:2] in "✓!✗":
            assert x[result_col - 1] == " " and x[result_col] != " ", x
        if x.startswith("   ├") or x.startswith("   └"):
            assert x[result_col - 1] == " " and x[result_col] != " ", x
    edges = {len(x) - len(x.lstrip()) for x in body if x and not x.startswith("   ")}
    assert edges == {1}, "the body has a single left edge"
    first_ink = min(len(r) - len(r.lstrip()) for r in screen.WORDMARK)
    assert first_ink == 1, "the body starts at the wordmark's left edge"
    blanks = [i for i, x in enumerate(lines) if x == ""]
    assert all(b + 1 not in blanks for b in blanks), "exactly one blank line between groups"
    hints = [x.index(h) for x in body for h in ("type /hooks once", "restart Cursor") if h in x]
    assert len(set(hints)) == 1, "hints share a column"


def test_memory_pick_strips_terminal_escapes():
    got = pick_memory([mem("use pnpm\x1b]0;pwned\x07 \x1b[2Jalways\x9b31m")])
    assert got and not any(ch in got for ch in "\x1b\x07\x9b")


def test_long_note_stays_on_one_row(final):
    """A note longer than the block is cut with an ellipsis: a wrapped tail would be drawn over by the next row."""
    state, end = final()
    state.steps[0].note = "found; background reading off (Claude Code 2.0.1 is older than 2.1.301: update it)"
    row = next(visible(x) for x in frame(end, state) if "Claude Code" in x and "found" in x)
    assert len(row) <= 68 and row.endswith("…")
