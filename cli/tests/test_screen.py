"""The setup screen's frames (spec 9.1, Tests)."""
import os
import re
from pathlib import Path

import pytest
from conftest import THREE, plan, scripted

from lflabs_memory_cli import screen
from lflabs_memory_cli.kip_art import SPRITES
from lflabs_memory_cli.screen import (LABEL, AppResult, Memory, ScreenState, cap_lit, done_at, frame, kip_at,
                                      pick_memory, post_xs, self_check_row, visible)

GOLDEN = Path(__file__).parent / "banner"
UPDATE = bool(os.environ.get("UPDATE_GOLDEN"))
TRY_PREFIX = "Try it:"
BRAILLE = tuple(chr(c) for c in range(0x2801, 0x2900))


def check_golden(name, lines):
    path = GOLDEN / f"{name}.txt"
    text = "\n".join(lines) + "\n"
    if UPDATE or not path.exists():
        path.write_text(text)
    assert text == path.read_text(), f"{name} differs from {path} (UPDATE_GOLDEN=1 to accept)"


def scene_times(state):
    """(mid-hop, mid-dive): halfway through the second hop, and Kip beak first into the water."""
    sc = screen._scene(state, screen._timeline(state))
    return sc.hops[1][1] + screen.HOP / 2, sc.dive + 0.4


def test_frames_golden():
    state = scripted()
    end = done_at(state)
    hop, dive = scene_times(state)
    for name, t in [("t0.4", 0.4), ("t1.0", 1.0), ("t2.0", 2.0), ("mid-download", 3.1), ("mid-hop", hop),
                    ("mid-dive", dive), ("final", end)]:
        check_golden(name, frame(t, state))
    check_golden("final-colour", [line.replace("\x1b", "\\e") for line in frame(end, scripted(color=True))])
    compact = scripted(height=30)
    check_golden("compact-final", frame(done_at(compact), compact))


def test_final_frame_matches_the_design():
    """The last frame at 100 x 46 is the prototype's (research/dawnmere-kip/term/final_frame.txt), line for line.
    Two rows differ on purpose: the tree's "how" lines up with the results (spec 9.1, One result column), and the
    self-check shows hundredths (decided 2026-10-28)."""
    design = (GOLDEN / "design-final.txt").read_text().splitlines()
    state = scripted(width=100, height=46)
    real = [visible(x) for x in frame(done_at(state), state)]
    assert len(real) == len(design) == 34
    for want, got in zip(design, real):
        if want.lstrip().startswith(("├", "└")):
            want = want[:17] + " " + want[17:]
        elif "Self-check" in want:
            want = want.replace("0.3 s", "0.34 s")
        assert got == want


def test_mid_download_shows_the_bar():
    row = next(visible(x) for x in frame(3.1, scripted()) if "Search models" in x)
    assert "─" * 20 in row and row.rstrip().endswith("/ 57 MB")
    coloured = next(x for x in frame(3.1, scripted(color=True)) if "Search models" in visible(x))
    assert f"38;5;{screen.ORANGE}m─" in coloured, "the bar fills in Kip's orange"


def body_lines(state, t):
    return [visible(x) for x in frame(t, state)]


def times(state):
    end = done_at(state)
    return [i / 20 for i in range(int(end * 20) + 2)]


def test_width():
    """The art block is 67 columns after a margin of 1. Only the "Try it" line is wider: it ends at column 79."""
    for kw in ({}, {"color": True}, {"check": 2.1}, {"memory": None}, {"apps": THREE[:1]}):
        state = scripted(**kw)
        for t in times(state):
            for line in body_lines(state, t):
                limit = 79 if line.lstrip().startswith(TRY_PREFIX) else 68
                assert len(line) <= limit, (kw, t, line)
    final = body_lines(scripted(), done_at(scripted()))
    assert len(next(x for x in final if TRY_PREFIX in x)) == 79
    narrow = scripted(width=72)
    assert all(len(x) <= 71 for x in body_lines(narrow, done_at(narrow)))


def test_posts_track_apps():
    """A cap turns orange, its name shows and Kip hops there only once that app's leaf has settled."""
    state = scripted()
    tl = screen._timeline(state)
    settled = [le for _, le in tl.leaves]
    xs = post_xs(3)
    assert xs == [46, 78, 108]
    for t in times(state):
        lit = cap_lit(state, t)
        names = body_lines(state, t)[11] if len(body_lines(state, t)) > 11 else ""
        x, y, sprite = kip_at(state, t)
        for i, name in enumerate(THREE):
            assert lit[i] == (t >= settled[i]), (t, i)
            assert (name in names) == (t >= settled[i]), (t, name, names)
        if t >= 1.3 and sprite:
            reached = [xs[i] for i in range(3) if t >= settled[i]]
            if not reached:
                assert (x, y) == (screen.STUMP, screen.POST_TOP), "Kip waits on the stump"
            else:
                assert x <= reached[-1], (t, x, "Kip is never ahead of the last connected app")

    none = scripted(apps=())
    for t in times(none):
        x, y, sprite = kip_at(none, t)
        if t >= 1.3:
            assert (x, y) == (screen.STUMP, screen.POST_TOP) and sprite in ("perch", "blink")
    assert not any("is now in" in x for x in body_lines(none, done_at(none)))


def test_kip_dives_and_comes_back_with_the_note():
    state = scripted()
    sc = screen._scene(state, screen._timeline(state))
    last = sc.hops[-1][3]
    assert kip_at(state, sc.dive + 0.4)[2] == "dive"
    assert kip_at(state, sc.dive + 0.7)[2] is None, "under the water"
    assert kip_at(state, done_at(state)) == (last, screen.POST_TOP, "fish")
    empty = scripted(memory=None)
    assert kip_at(empty, done_at(empty))[2] == "perch", "no note: no fish"


@pytest.mark.parametrize("n", [1, 2, 3, 4, 6])
def test_ending_apps(n):
    names = ["Claude Code", "Codex", "Cursor", "Windsurf", "VS Code", "Gemini CLI"][:n]
    state = scripted(apps=names)
    lines = body_lines(state, done_at(state))
    xs = post_xs(n)
    assert len(xs) == (3 if n > 4 else n)
    assert all(screen.STUMP + 2 < x and x + 2 < screen.BLOCK * 2 for x in xs), "every post inside the block"
    assert all(x % 2 == 0 for x in xs), "a post fills one cell"
    label = lines[11]
    assert len(label) <= 68
    shown = names[:3] if n > 4 else names
    assert all(name in label for name in shown)
    if n == 6:
        assert label.endswith("+3 more") and "Windsurf" not in label
    tail = {1: "  is saved", 2: "  is now in both"}.get(n, f"  is now in all {n}")
    assert any(tail in x for x in lines)
    if n == 1:
        assert any("Add Cursor or Codex later: dawnmere setup" in x for x in lines)
    assert kip_at(state, done_at(state))[0] == xs[-1], "Kip dives at the last post"


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
    assert "  What you tell Claude Code or Codex now reaches the others." in lines
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

    # non-UTF-8: no art yet (the ASCII Kip is not drawn), the spaced name, all ASCII, no animation
    state = scripted(unicode=False, color=True)
    for t in (0.4, done_at(state)):
        lines = body_lines(state, t)
        assert all(x.isascii() for x in lines)
        assert lines[:3] == ["  d a w n m e r e", "  " + screen.TAGLINE, ""]

    # Reduce Motion: still frames. Kip on the post of the last connected app, at the end holding the fish
    still = scripted(motion=False)
    end = done_at(still)
    assert end == screen._timeline(still).end, "no ending to wait for: it is drawn at once"
    assert frame(2.6, still) == frame(2.61, still), "nothing moves between steps"
    settled = [le for _, le in screen._timeline(still).leaves]
    assert kip_at(still, settled[0] - 0.01) == (screen.STUMP, screen.POST_TOP, "perch")
    assert kip_at(still, settled[1]) == (78, screen.POST_TOP, "perch"), "no hop: Kip is just there"
    assert kip_at(still, end) == (108, screen.POST_TOP, "fish")
    final = body_lines(still, end)
    assert any("Dawnmere is on." in x for x in final)
    assert any(x.strip().startswith("•") for x in body_lines(still, 3.0)), "a still mark, not a spinner"

    # NO_COLOR: the same frames, without a colour code
    assert not any("\x1b[38;5" in x for x in frame(done_at(scripted()), scripted()))


@pytest.mark.parametrize("display", [{"width": 60}, {"height": 34}, {"height": 24}])
def test_compact_header(display):
    """Under 70 columns or under 35 rows: one name line and the tagline, then the steps. No Kip, no wordmark."""
    state = scripted(**display)
    for t in times(state):
        lines = body_lines(state, t)
        assert not any(ch in x for x in lines for ch in BRAILLE if ch not in screen.SPIN), (t, "no art")
    lines = body_lines(state, done_at(state))
    assert lines[:4] == ["  dawnmere", "  " + screen.TAGLINE, "", "  ✓ Claude Code     found, logged in"]
    assert "  “always run tests before committing”  is now in all 3" in lines
    assert len(lines) + 1 <= state.height


def test_full_header_needs_35_rows():
    assert screen._header(scripted(height=35)) == "full"
    assert screen._header(scripted(height=34)) == "compact"
    assert screen._header(scripted(height=35, apps=["Claude Code", "Codex", "Cursor", "Windsurf"])) == "compact"
    full = scripted(height=35)
    assert len(frame(done_at(full), full)) + 1 == 35, "the screen and the cursor's line fill the window exactly"


def test_plain_mode_has_no_escapes():
    state = scripted(plain=True, color=True)
    lines = frame(done_at(state), state)
    assert lines[0] == "[ok] Claude Code: found, logged in" and "Dawnmere is on." in lines
    assert not any("\x1b" in x or any(ch in x for ch in BRAILLE) for x in lines)


def test_self_check_row(final):
    assert self_check_row(0.34) == ("ok", "recall in 0.34 s")
    state, end = final(check=0.34)
    assert "  ✓ Self-check      recall in 0.34 s" in body_lines(state, end)

    state, end = final(check=2.1)
    lines = body_lines(state, end)
    assert "  ! Self-check      recall in 2.10 s (slow: dawnmere doctor)" in lines
    assert any("Dawnmere is on." in x for x in lines), "setup still finishes"
    coloured = frame(end, scripted(check=2.1, color=True))
    assert any(f"38;5;{screen.AMBER}m!" in x for x in coloured)

    state, end = final(fail=True)
    lines = body_lines(state, end)
    assert "  ✗ Self-check      the memory service did not answer" in lines
    assert not any("Dawnmere is on." in x or "Try it" in x or "is now in" in x for x in lines)
    stays = kip_at(state, end)
    assert stays == kip_at(state, end + 5) and stays[0] == 108 and stays[2] in ("perch", "blink"), "Kip does not dive"
    assert all(kip_at(state, end + k / 10)[2] != "dive" for k in range(60))


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
        assert not any(ch in x for x in lines for ch in BRAILLE if ch not in screen.SPIN), "no Kip or wordmark"
    lines = body_lines(state, done_at(state))
    assert lines[0].startswith("  ✓ Claude Code") and lines[-1] == "  Dawnmere is on."


def test_apps_arrive_one_at_a_time():
    state = scripted()
    tl = screen._timeline(state)
    starts = [ls for ls, _ in tl.leaves]
    for k in range(3):
        t = starts[k] + 0.01
        lines = body_lines(state, t)
        leaves = [x for x in lines if x.startswith("    ├") or x.startswith("    └")]
        assert len(leaves) == k + 1, (t, lines)
        assert all("Your apps" not in x or f"{k} of 3" in x for x in lines if "Your apps" in x)
        assert any(c in leaves[-1] for c in screen.SPIN), "the newest leaf spins"
        assert all(not any(c in x for c in screen.SPIN) for x in leaves[:-1]), "earlier leaves settled"
        for later in THREE[k + 1:]:
            assert not any(later in x for x in leaves), f"{later} appeared before its wiring started"
            assert later not in lines[11], f"{later}'s name appeared under its post before it was connected"
    assert any("1 of 3" in x for x in body_lines(state, starts[1] + 0.01))


def test_alignment(final):
    state, end = final()
    lines = body_lines(state, end)
    body = lines[lines.index("  ✓ Claude Code     found, logged in"):]
    result_col = 2 + 2 + LABEL
    for x in body:
        if x[2:3] and x[2:3] in "✓!✗":
            assert x[result_col - 1] == " " and x[result_col] != " ", x
        if x.startswith("    ├") or x.startswith("    └"):
            assert x[result_col - 1] == " " and x[result_col] != " ", x
    edges = {len(x) - len(x.lstrip()) for x in body if x and not x.startswith("    ")}
    assert edges == {2}, "the body has a single left edge"
    blanks = [i for i, x in enumerate(lines) if x == ""]
    assert all(b + 1 not in blanks for b in blanks), "exactly one blank line between groups"
    hints = [x.index(h) for x in body for h in ("type /hooks once", "restart Cursor") if h in x]
    assert len(set(hints)) == 1, "hints share a column"
    tag = next(x for x in lines if screen.TAGLINE in x)
    left, right = len(tag) - len(tag.lstrip()) - 1, screen.BLOCK - len(tag.strip()) - (len(tag) - len(tag.lstrip()) - 1)
    assert abs(left - right) <= 1, "the header is centred on the block"


def test_sprites_on_model():
    """In every perched pose the eye is a hole inside the orange band, and Kip stands on its feet."""
    for name in ("perch", "fish"):
        rows = SPRITES[name]["rows"]
        band = [y for y, r in enumerate(rows) if re.search(r"o\.{1,3}o", r)]
        assert band, f"{name}: no eye hole in the band"
        y = band[0]
        assert "b" in rows[y - 1] and "o" in rows[y + 1], f"{name}: the hole is inside Kip, not at an edge"
        assert SPRITES[name]["ay"] == len(rows) - 1, "the anchor is the feet"


def test_memory_pick_strips_terminal_escapes():
    got = pick_memory([mem("use pnpm\x1b]0;pwned\x07 \x1b[2Jalways\x9b31m")])
    assert got and not any(ch in got for ch in "\x1b\x07\x9b")


def test_long_note_stays_on_one_row(final):
    """A note longer than the block is cut with an ellipsis: a wrapped tail would be drawn over by the next row."""
    state, end = final()
    state.steps[0].note = "found; background reading off (Claude Code 2.0.1 is older than 2.1.301: update it)"
    row = next(visible(x) for x in frame(end, state) if "Claude Code" in x and "found" in x)
    assert len(row) <= 68 and row.endswith("…")


def test_a_problem_replaces_the_success_line():
    """Setup worked but the apps cannot use memory's tools (no Node.js): the end says so, not "Dawnmere is on."."""
    problem = "Node.js is not installed: your apps cannot use memory's tools until you install Node.js 18 or later " \
              "from nodejs.org."
    for display in ({}, {"plain": True}, {"intro": False}, {"width": 60}):
        state = scripted(**display)
        state.problem = problem
        lines = [visible(x) for x in frame(done_at(state), state)]
        text = " ".join(" ".join(line.split()) for line in lines)
        assert "Dawnmere is on." not in text and TRY_PREFIX not in text and "reaches the others" not in text
        assert problem in text.replace("! ", ""), display
        assert state.plain or all(len(line) <= state.width for line in lines), display  # plain lines never wrap


@pytest.mark.parametrize("backend_name,logged_in,version", [("claude-cli", False, "2.1.301"),
                                                           ("claude-cli", True, "2.1.301"),
                                                           ("anthropic-api", None, "2.1.301"),
                                                           ("none", None, "2.1.301"), ("none", None, None)])
def test_claude_code_row_fits_80_columns(final, backend_name, logged_in, version):
    """Setup's own Claude Code notes are never cut at 80 columns ("log in to start reading (claude, then…" was)."""
    from lflabs_memory_cli import backend, setup
    a = setup.Answers()
    a.backend = backend_name
    a.claude = backend.Status("claude-cli", True, version, logged_in, usable=True)
    got = []

    class UI:
        def step(self, label, status, note=None, **kw):
            got.append((status, note))
    setup.RealSetup.step_claude(type("S", (), {"a": a})(), UI())
    status, note = got[-1]
    state, end = final(width=80)
    state.steps[0].status, state.steps[0].note = status, note
    row = next(visible(x) for x in frame(end, state) if "Claude Code" in x and note in x)
    assert len(row) <= 80 and not row.endswith("…")


def test_closing_lines_name_only_apps_whose_typed_notes_travel():
    """Windsurf, Gemini CLI and VS Code have no prompt hook: what is told to them waits for confirmation."""
    from types import SimpleNamespace
    from lflabs_memory_cli import screen
    plain = lambda xs: [re.sub(r"\x1b\[[0-9;]*m", "", x) for x in xs]
    st = SimpleNamespace(memory=None, color=False)
    assert plain(screen._memory_lines(st, ["Codex", "Cursor", "Windsurf", "Gemini CLI", "VS Code"])) == \
        ["  What you tell Codex now reaches the others."]
    assert plain(screen._memory_lines(st, ["Cursor", "Gemini CLI"])) == ["  Your apps now share one memory."]
    lines, _ = screen._try_lines(120, ["Windsurf", "Codex", "Cursor"])
    assert lines[0].startswith("Try it: in Codex,")
