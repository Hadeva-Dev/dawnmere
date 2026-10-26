"""Fake setup work for `setup --demo`: the real screen, driven by timers instead of real work.

A setup is anything with plan() -> list[Step], expect_apps, and run(ui) -> bool (True when it worked), calling
ui.step / ui.apps / ui.memory as it goes. The real setup (spec 9.2) plugs in the same way.
"""
import time

from .screen import AppResult, Memory, Step, pick_memory, self_check_row

SCENARIOS = ("default", "slow", "fail", "one", "six", "new", "rerun")

MB = 1_000_000
NOTES = [  # stands in for the Claude Code memory files setup imports
    Memory("always run tests before committing", "feedback", "prefs", created=3),
    Memory("staging DB is on port 6543", "project", "projects", created=2),
    Memory("Call me at +1 415 555 0134 after 6", "user", "personal", created=1),
]
APPS = {
    "Claude Code": ("plugin", None),
    "Codex": ("MCP + hook", "type /hooks once"),
    "Cursor": ("MCP", "restart Cursor"),
    "Windsurf": ("MCP", None),
    "VS Code": ("MCP", None),
    "Gemini CLI": ("MCP", None),
}


class FakeSetup:
    def __init__(self, scenario="default", speed=1.0):
        self.scenario = scenario
        self.speed = speed
        names = list(APPS)
        self.app_names = names[:1] if scenario == "one" else names if scenario == "six" else names[:3]
        self.expect_apps = len(self.app_names)

    def plan(self):
        return [Step("Claude Code"), Step("Search models", weight=3), Step("Memory service"),
                Step("Your apps", weight=2, apps=True), Step("Your notes"), Step("Self-check")]

    def _wait(self, seconds):
        time.sleep(seconds * self.speed)

    def run(self, ui):
        ui.step("Claude Code", "running")
        self._wait(0.05)
        ui.step("Claude Code", "ok", "found, logged in")

        total = 57 * MB
        ui.step("Search models", "running", progress=(0, total))
        for i in range(1, 41):
            self._wait(0.04)
            ui.step("Search models", "running", progress=(total * i // 40, total))
        ui.step("Search models", "ok", "57 MB, checked")

        ui.step("Memory service", "running")
        self._wait(0.3)
        ui.step("Memory service", "ok", "running")

        ui.step("Your apps", "running")
        apps = [AppResult(n, *APPS[n]) for n in self.app_names]
        for a in apps:
            a.status = "running"
            ui.apps(apps)
            self._wait(0.15)
            a.status = "ok"
            ui.apps(apps)
        ui.step("Your apps", "ok", "connected")

        ui.step("Your notes", "running")
        self._wait(0.1)
        if self.scenario == "new":
            ui.step("Your notes", "ok", "none to import yet")
        else:
            ui.memory(pick_memory(NOTES))
            ui.step("Your notes", "ok", "14 imported from Claude Code")

        ui.step("Self-check", "running")
        self._wait(0.3)
        if self.scenario == "fail":
            ui.step("Self-check", "failed", "the memory service did not answer")
            return False
        ui.step("Self-check", *self_check_row(2.1 if self.scenario == "slow" else 0.34))
        return True
