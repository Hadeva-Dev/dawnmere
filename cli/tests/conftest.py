"""Scripted setups: every step and app with fixed times, so frames are reproducible."""
import pytest

from lflabs_memory_cli.screen import AppResult, ScreenState, Step, done_at, self_check_row

THREE = ("Claude Code", "Codex", "Cursor")
HOWS = {"Claude Code": ("plugin", None), "Codex": ("MCP + hook", "type /hooks once"),
        "Cursor": ("MCP", "restart Cursor")}
MB = 1_000_000


def plan():
    return [Step("Claude Code"), Step("Search models", weight=3), Step("Memory service"),
            Step("Your apps", weight=2, apps=True), Step("Your notes"), Step("Self-check")]


def scripted(apps=THREE, memory="always run tests before committing", check=0.34, fail=False, until=None,
             start=2.2, **display):
    """A setup that did its work at fixed times on the screen clock: the download runs 2.25 to 4.0 s.
    until: stop the script at this time (steps not started yet stay pending)."""
    display = {"color": False, "width": 80, "height": 40, **display}
    state = ScreenState(steps=plan(), expect_apps=len(apps), **display)
    steps = {s.label: s for s in state.steps}
    t = start

    def run(label, dur, note, status="ok"):
        nonlocal t
        s = steps[label]
        if until is not None and t > until:
            return False
        s.started, s.status = t, "running"
        if until is not None and t + dur > until:
            return False
        t += dur
        s.ended, s.status, s.note = t, status, note
        return True

    if not run("Claude Code", 0.05, "found, logged in"):
        return state
    dl = steps["Search models"]
    dl.started, dl.status = t, "running"
    for i in range(36):
        at = t + i * 0.05
        if until is not None and at > until:
            return state
        dl.progress.append((at, 57 * MB * i // 35, 57 * MB))
    t += 1.75
    dl.ended, dl.status, dl.note = t, "ok", "57 MB, checked"
    if not run("Memory service", 0.3, "running"):
        return state
    parent = steps["Your apps"]
    parent.started, parent.status = t, "running"
    for name in apps:
        if until is not None and t > until:
            return state
        how, hint = HOWS.get(name, ("MCP", None))
        a = AppResult(name, how, hint, status="running", started=t)
        state.apps.append(a)
        if until is not None and t + 0.2 > until:
            return state
        t += 0.2
        a.ended, a.status = t, "ok"
    parent.ended, parent.status, parent.note = t, "ok", "connected"
    if not run("Your notes", 0.1, "14 imported from Claude Code"):
        return state
    state.memory = memory
    if fail:
        run("Self-check", 0.3, "the memory service did not answer", status="failed")
    elif not run("Self-check", 0.3, self_check_row(check)[1], status=self_check_row(check)[0]):
        return state
    state.finished = t
    return state


@pytest.fixture
def final():
    def make(**kw):
        state = scripted(**kw)
        return state, done_at(state)
    return make
