"""Fake programs on PATH (claude, launchctl, security, uv, codex): each logs its argv and answers by rule."""
import json
import os
import stat
import sys

SCRIPT = """#!{python}
import json, os, sys
prog = os.path.basename(sys argv0)
argv = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({{"prog": prog, "argv": argv, "stdin": "" if sys.stdin.isatty() else sys.stdin.read(),
                        "path": os.environ.get("PATH", "")}}) + "\\n")
rules = json.load(open(os.environ["FAKE_RULES"])).get(prog, [])
for prefix, code, out in rules:
    if argv[:len(prefix)] == prefix:
        sys.stdout.write(out)
        sys.exit(code)
sys.exit(0)
""".replace("sys argv0", "sys.argv[0]")


class Fakes:
    def __init__(self, root, progs=("claude", "launchctl", "security", "uv", "codex", "plutil")):
        self.bin = root / "fakebin"
        self.bin.mkdir()
        self.log = root / "fake.log"
        self.rules_file = root / "fake-rules.json"
        self.rules = {}
        self.save()
        for p in progs:
            self.add(p)

    def add(self, prog):
        f = self.bin / prog
        f.write_text(SCRIPT.format(python=sys.executable))
        f.chmod(f.stat().st_mode | stat.S_IXUSR)

    def remove(self, prog):
        (self.bin / prog).unlink()

    def on(self, prog, prefix, code=0, out=""):
        """argv starting with prefix: exit code, stdout. Earlier rules win."""
        self.rules.setdefault(prog, []).append([list(prefix), code, out])
        self.save()

    def save(self):
        self.rules_file.write_text(json.dumps(self.rules))

    def calls(self, prog=None):
        if not self.log.exists():
            return []
        rows = [json.loads(line) for line in self.log.read_text().splitlines()]
        return [r["argv"] for r in rows if prog is None or r["prog"] == prog]

    def paths(self, prog):
        """(argv, PATH) of each call to prog."""
        if not self.log.exists():
            return []
        rows = [json.loads(line) for line in self.log.read_text().splitlines()]
        return [(r["argv"], r.get("path", "")) for r in rows if r["prog"] == prog]

    def env(self, monkeypatch):
        monkeypatch.setenv("PATH", f"{self.bin}{os.pathsep}/usr/bin{os.pathsep}/bin")
        monkeypatch.setenv("FAKE_LOG", str(self.log))
        monkeypatch.setenv("FAKE_RULES", str(self.rules_file))
