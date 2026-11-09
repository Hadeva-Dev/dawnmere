"""dawnmere setup (spec 9.2, Task 9): a temp HOME, fake claude, launchctl, security, zsh and engine."""
import hashlib
import json
import os
import shutil
import socketserver
import stat
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import pytest
from conftest import FakeConnector

from lflabs_memory_cli import apps, launchd, layout, main as cli, models, setup
from lflabs_memory_cli.run import Result

HERE = Path(__file__).parent


@pytest.fixture
def box(mac, monkeypatch, tmp_path):
    """Everything setup talks to, faked: claude (logged in), the engine, its two sockets, a models release."""
    short = Path(tempfile.mkdtemp(prefix="lfs", dir="/tmp"))
    data = short / "data"
    monkeypatch.setenv("LFLABS_MEMORY_HOME", str(data))
    state = short / "engine-state.json"
    monkeypatch.setenv("FAKE_ENGINE_STATE", str(state))
    engine = mac.bin / "lflabs-memory"
    engine.write_text(f"#!{sys.executable}\n" + (HERE / "fake_engine.py").read_text())
    engine.chmod(engine.stat().st_mode | stat.S_IXUSR)
    mac.add("zsh")
    for prog in ("node", "npx"):
        mac.add(prog)
    mac.on("node", ["--version"], 0, "v22.1.0\n")
    mac.on("claude", ["--version"], 0, "2.1.301 (Claude Code)\n")
    mac.on("claude", ["-p"], 0, '{"is_error": false, "result": "ok"}')
    mac.on("claude", ["mcp", "get"], 1, "")
    mac.on("launchctl", ["print"], 113, "")

    def recall(req):
        if req["tool"] == "ping":
            return {"ok": True, "text": "Dawnmere 0.2.0"}
        fact = json.loads(state.read_text()).get("fact", "") if state.exists() else ""
        return {"ok": True, "text": f"#7 {fact}"}
    conn = FakeConnector(recall)
    monkeypatch.setenv("LFLABS_MEMORY_SOCKET", conn.path)
    data.mkdir()

    class Accept(socketserver.BaseRequestHandler):
        def handle(self):
            pass
    eng_sock = socketserver.ThreadingUnixStreamServer(str(data / "engine.sock"), Accept)
    threading.Thread(target=eng_sock.serve_forever, daemon=True).start()
    rel = tmp_path / "models-release"
    files = {}
    for name in ("embed", "rerank"):
        body = f"{name} weights".encode() * 50
        (rel / name).mkdir(parents=True)
        (rel / name / "model.onnx").write_bytes(body)
        files[name] = [{"file": "model.onnx", "url": (rel / name / "model.onnx").as_uri(), "size": len(body),
                        "sha256": hashlib.sha256(body).hexdigest()}]
    monkeypatch.setattr(models, "manifest", lambda: {"release": "models-x", "models": files})
    monkeypatch.setattr(setup, "other_engine", lambda: None)  # the fake connector stands in for our own service
    monkeypatch.setattr(setup, "READY_WAIT", 3.0)
    for d in (".claude", ".codex", ".cursor"):
        (mac.home / d).mkdir()
    mac.data = data
    yield mac
    eng_sock.shutdown()
    eng_sock.server_close()
    conn.close()
    shutil.rmtree(short, ignore_errors=True)


def run_setup(*flags):
    args = cli.parser().parse_args(["setup", "--yes", "--plain", *flags])
    out = []
    return setup.main(args, say=out.append), "\n".join(out)


def tree(home):
    """Every file under home with its bytes (backups included)."""
    return {str(p.relative_to(home)): p.read_bytes() for p in sorted(home.rglob("*")) if p.is_file()}


def test_onboarding_text_golden():
    assert setup.onboarding() == """\
Dawnmere gives Claude Code, Codex and Cursor one shared memory on this Mac.

Your memory is one file here, never uploaded. After a Claude Code session goes
quiet, your own model (your Claude plan or API key) reads the conversation and
keeps what is worth remembering. Nothing goes to LF Labs. No usage data, ever.

Setup adds Dawnmere to Claude Code, Codex and Cursor, backing up every file it
touches, and starts a small background service that keeps search fast.
"dawnmere uninstall" puts everything back.
"""
    assert max(len(line) for line in setup.onboarding().splitlines()) <= 78


def test_setup_end_to_end(box, capsys):
    code, out = run_setup()
    shown = capsys.readouterr().out
    assert code == 0, out + shown
    assert "[ok] Self-check: recall in" in shown and "Dawnmere is on." in shown
    assert "Background reading: your Claude plan (Haiku), up to 200 calls a day" in out
    assert ["plugin", "install", "lflabs-memory@lflabs", "--scope", "user", "-y"] in box.calls("claude")
    assert "dawnmere-connector@0.1.0" in (box.home / ".codex/config.toml").read_text()
    assert "hook-cursor-start" in (box.home / ".cursor/hooks.json").read_text()
    assert (layout.data_dir() / "config.toml").read_text().startswith('version = 1\nprofile = "generic"')
    assert oct(os.stat(layout.data_dir() / "config.toml").st_mode & 0o777) == "0o600"
    assert models.check(models.manifest()) == {"embed": "ok", "rerank": "ok"}
    assert any(c[:1] == ["bootstrap"] for c in box.calls("launchctl"))
    assert ["purge", "7"] in box.calls("lflabs-memory"), "the self-check's memory is deleted for good"


def test_setup_dry_run_lists_changes(box):
    before = tree(box.home)
    (box.home / ".codex/config.toml").write_text("model = 'o5'\n")
    before = tree(box.home)
    code, out = run_setup("--dry-run")
    assert code == 0
    assert tree(box.home) == before and not (layout.data_dir() / "config.toml").exists()
    assert box.calls("launchctl") == [] and not [c for c in box.calls("claude") if c[:1] == ["plugin"]]
    for line in ("~/.codex/config.toml: add [mcp_servers.lflabs-memory]", 'args = ["-y", "dawnmere-connector@0.1.0"]',
                 "~/.cursor/mcp.json: add mcpServers.\"lflabs-memory\"", "claude plugin install lflabs-memory@lflabs",
                 'LFLABS_MEMORY_CLIENT = "codex"', "hook-cursor-start"):
        assert line in out, line


def test_setup_idempotent(box, capsys):
    assert run_setup()[0] == 0
    first = tree(box.home)
    record = json.loads(layout.install_json().read_text())
    box.on("claude", ["plugin", "list"], 0, "lflabs-memory@lflabs 0.1.0\n")
    assert run_setup()[0] == 0
    assert tree(box.home) == first, "a second run adds nothing and makes no new backups"
    assert json.loads(layout.install_json().read_text())["files"] == record["files"]


def test_setup_leaves_jsonc_alone(box, capsys):
    jsonc = '// my servers\n{"mcpServers": {}}\n'
    (box.home / ".cursor/mcp.json").write_text(jsonc)
    code, out = run_setup()
    assert code == 0
    assert (box.home / ".cursor/mcp.json").read_text() == jsonc
    assert "~/.cursor/mcp.json: is not plain JSON (comments?): left alone; add this by hand" in out
    assert '"dawnmere-connector@0.1.0"' in out, "the lines to add are printed"


def test_plugin_fallback_when_plugin_cli_fails(box, capsys):
    box.on("claude", ["plugin", "marketplace"], 1, "")
    assert run_setup()[0] == 0
    calls = box.calls("claude")
    assert ["mcp", "add", "--scope", "user", "--transport", "stdio", "lflabs-memory", "--", "npx", "-y",
            "dawnmere-connector@0.1.0"] in calls
    hooks = json.loads((box.home / ".claude/settings.json").read_text())["hooks"]
    assert set(hooks) == {"UserPromptSubmit", "SessionStart", "Stop", "SessionEnd"}
    assert hooks["UserPromptSubmit"][0]["hooks"][0]["command"] == "lflabs-memory hook-prompt"


def test_setup_writes_through_symlink(box, capsys):
    box.on("claude", ["plugin", "marketplace"], 1, "")
    dotfiles = box.home / "dotfiles"
    dotfiles.mkdir()
    (dotfiles / "settings.json").write_text('{"theme": "dark"}\n')
    (box.home / ".claude/settings.json").symlink_to(dotfiles / "settings.json")
    assert run_setup()[0] == 0
    assert (box.home / ".claude/settings.json").is_symlink()
    assert "hook-prompt" in (dotfiles / "settings.json").read_text()


def test_codex_toml_append_keeps_line_endings(tmp_path):
    f = tmp_path / "config.toml"
    f.write_bytes(b'model = "o5"\r\n')
    p = apps.plan_codex_toml(f)
    assert p.state == "add" and "\n" not in p.new.replace("\r\n", "")


def test_setup_refuses_second_engine(mac, monkeypatch, connector):
    """Another engine answers on the connector socket and our service is not loaded: refuse before any change."""
    monkeypatch.setenv("LFLABS_MEMORY_HOME", str(mac.home / "data"))
    mac.on("launchctl", ["print"], 113, "")
    code, out = run_setup()
    assert code == 1 and "Another memory engine is already running on this Mac (Dawnmere 0.2.0)" in out
    assert not (mac.home / "data").exists() and not layout.plist_path().exists()


def test_self_check_failure_hides_try_it(box, capsys):
    json.dump({"refuse": True}, open(os.environ["FAKE_ENGINE_STATE"], "w"))
    code, out = run_setup()
    shown = capsys.readouterr().out
    assert code == 1
    assert '[fail] Self-check: a typed "remember that" was not saved' in shown
    assert "Try it" not in shown and "Dawnmere is on." not in shown


def test_plist_lint():
    text = launchd.render("/Users/a b/.local/bin/lflabs-memory", Path("/Users/a&b"), Path("/Users/a&b/data"))
    assert "<string>/Users/a&amp;b/data</string>" in text
    with tempfile.NamedTemporaryFile("w", suffix=".plist", delete=False) as f:
        f.write(text)
    try:
        r = subprocess.run(["/usr/bin/plutil", "-lint", f.name], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout
    finally:
        os.unlink(f.name)


def test_install_record_complete(box, capsys):
    originals = {}
    (box.home / ".codex/config.toml").write_text('model = "o5"\n')
    (box.home / ".cursor/mcp.json").write_text('{"mcpServers": {}}\n')
    for rel in (".codex/config.toml", ".cursor/mcp.json"):
        originals[str(box.home / rel)] = (box.home / rel).read_bytes()
    assert run_setup()[0] == 0
    record = json.loads(layout.install_json().read_text())
    changed = {e["path"]: e for e in record["files"]}
    for path in (box.home / ".codex/config.toml", box.home / ".codex/hooks.json", box.home / ".cursor/mcp.json",
                 box.home / ".cursor/hooks.json"):
        e = changed[str(path)]
        assert e["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        if str(path) in originals:
            assert Path(e["backup"]).read_bytes() == originals[str(path)], "the backup is the file before setup"
        else:
            assert e["created"] and e["backup"] is None
    assert any(c["argv"][:3] == ["claude", "plugin", "install"] for c in record["commands"])
    assert record["plist"] == str(layout.plist_path())


def test_setup_then_uninstall_leaves_nothing(box, capsys, monkeypatch):
    """A3 in miniature: every app file back as it was, no agent, no data, no Keychain item; only backups remain."""
    from lflabs_memory_cli import prompt, uninstall
    (box.home / ".codex/config.toml").write_bytes(b'model = "o5"\r\n')
    (box.home / ".cursor/mcp.json").write_text('{\n  "mcpServers": {"gh": {"command": "gh"}}\n}\n')
    (box.home / ".claude/settings.json").write_text('{"theme": "dark"}\n')
    before = tree(box.home)
    box.on("claude", ["plugin", "marketplace"], 1, "")  # the fallback: it writes settings.json too
    assert run_setup()[0] == 0
    assert tree(box.home) != before
    monkeypatch.setattr(prompt, "yes_no", lambda q, default, assume=None: True)  # "Delete your memory too?" yes
    assert uninstall.main(out=lambda s: None) == 0
    after = {k: v for k, v in tree(box.home).items() if ".lflabs-backup-" not in k}
    assert after == before
    assert not layout.data_dir().exists() and not layout.plist_path().exists()
    assert ["mcp", "remove", "--scope", "user", "lflabs-memory"] in box.calls("claude")


def answering(monkeypatch, answers):
    """prompt.yes_no answering by question (substring -> answer); the rest take their default. Records the questions."""
    from lflabs_memory_cli import prompt
    asked = []

    def yes_no(q, default, assume=None):
        asked.append(q)
        for part, answer in answers.items():
            if part in q:
                return answer
        return default if assume is None else assume
    monkeypatch.setattr(prompt, "yes_no", yes_no)
    return asked


def test_cursor_starts_at_work_only(box, capsys):
    assert run_setup()[0] == 0
    entry = json.loads((box.home / ".cursor/mcp.json").read_text())["mcpServers"]["lflabs-memory"]
    assert entry["env"] == {"LFLABS_MEMORY_CLIENT": "cursor"}, "no key: held to work only"
    hook = json.loads((box.home / ".cursor/hooks.json").read_text())["hooks"]["sessionStart"][0]["command"]
    assert hook.startswith("LFLABS_MEMORY_CLIENT=cursor "), "its start block is filtered as Cursor's"
    assert not [c for c in box.calls("lflabs-memory") if c[:2] == ["clients", "level"]]


def test_cursor_personal_notes_when_asked(box, monkeypatch, capsys):
    from lflabs_memory_cli import uninstall
    asked = answering(monkeypatch, {"Let Cursor see your personal notes too?": True})
    code, out = run_setup()
    shown = capsys.readouterr().out
    assert code == 0, out + shown
    assert any("Let Cursor see your personal notes too?" in q for q in asked)
    entry = json.loads((box.home / ".cursor/mcp.json").read_text())["mcpServers"]["lflabs-memory"]
    key = entry["env"]["LFLABS_MEMORY_CLIENT_KEY"]
    assert len(key) >= 24
    hook = json.loads((box.home / ".cursor/hooks.json").read_text())["hooks"]["sessionStart"][0]["command"]
    assert hook.startswith("LFLABS_MEMORY_CLIENT=cursor ") and key not in hook, "never a key on a command line"
    assert oct((box.home / ".cursor/mcp.json").stat().st_mode & 0o777) == "0o600", "the file with the key: owner only"
    clients = json.loads((box.data / "clients.json").read_text())["clients"]
    assert clients["cursor"]["key_sha256"] and key not in json.dumps(clients), "the engine keeps only its hash"
    assert ["clients", "level", "cursor", "everything"] in box.calls("lflabs-memory")
    for text in (out, shown, layout.install_json().read_text()):
        assert key not in text, "the key is never shown or recorded"
    assert "MCP (all)" in shown or "Cursor: MCP (all)" in shown
    assert uninstall.main(keep_data=True, out=lambda s: None) == 0
    assert key not in (box.home / ".cursor/mcp.json").read_text() if (box.home / ".cursor/mcp.json").exists() else True


def test_plan_first_even_when_logged_out(box, monkeypatch, capsys):
    box.rules["claude"] = [r for r in box.rules["claude"] if r[0][:1] != ["-p"]]
    box.on("claude", ["-p"], 1, "Please run /login")
    asked = answering(monkeypatch, {})
    code, out = run_setup()
    assert 'backend = "claude-cli"' in (layout.data_dir() / "config.toml").read_text()
    assert "Claude Code is not logged in yet: run claude, then /login" in out
    assert not any("API key" in q for q in asked), "an API key is never offered while the plan can be used"


def test_no_api_key_unless_asked_for(box, monkeypatch, capsys):
    """No Claude Code: with --yes it is none mode, never the API; the API question is asked only interactively, and
    a no keeps none mode."""
    box.remove("claude")
    asked = answering(monkeypatch, {})
    run_setup()
    assert 'backend = "none"' in (layout.data_dir() / "config.toml").read_text()
    assert not any("API key" in q for q in asked)
    args = cli.parser().parse_args(["setup", "--plain", "--dry-run"])
    out = []
    a = setup.ask(args, out.append)
    assert a.backend == "none" and any("Anthropic API key" in q for q in asked)


def test_access_command(box, monkeypatch, capsys):
    from lflabs_memory_cli import access
    out = []
    eng = layout.engine_bin()
    assert access.main("cursor", None, eng, say=out.append) == 1
    assert out[-1] == "Memory is not set up yet: run dawnmere setup first.", "not \"Cursor sees not set up\""
    assert run_setup()[0] == 0
    assert access.main("cursor", "everything", eng, say=out.append) == 0
    assert out[-1] == "Cursor now sees everything, personal notes too. Restart Cursor to load it."
    entry = json.loads((box.home / ".cursor/mcp.json").read_text())["mcpServers"]["lflabs-memory"]
    assert "LFLABS_MEMORY_CLIENT_KEY" in entry["env"]
    assert access.main("cursor", "work", eng, say=out.append) == 0 and out[-1] == "Cursor now sees work notes only."
    assert access.main("codex", "everything", eng, say=out.append) == 1
    assert access.main("cursor", None, eng, say=out.append) == 0
    assert out[-1].startswith("Cursor sees ") and "dawnmere access cursor everything | nothing-personal" in out[-1]


def test_node_missing_is_said(box, capsys):
    """No npx: setup still works (the hooks need no Node), says the apps' memory tools wait for Node.js, and its
    final screen repeats that instead of saying Dawnmere is on."""
    box.remove("node")
    box.remove("npx")
    code, out = run_setup()
    shown = capsys.readouterr().out
    assert code == 0 and "Node.js is not installed" in out
    assert "Dawnmere is on." not in shown and "Try it" not in shown
    assert "your apps cannot use memory's tools until you install Node.js 18 or later from nodejs.org" in shown
    box.add("npx")
    box.add("node")
    box.rules["node"] = [[["--version"], 0, "v16.20.2\n"]]
    box.save()
    code, out = run_setup()
    shown = capsys.readouterr().out
    assert "Node.js v16.20.2 is too old" in out and "Dawnmere is on." not in shown
    box.rules["node"] = [[["--version"], 0, "v22.1.0\n"]]
    box.save()
    code, out = run_setup()
    shown = capsys.readouterr().out
    assert "Node.js" not in out + shown and "Dawnmere is on." in shown


def test_service_reload_waits_for_the_old_agent_to_leave(box, monkeypatch):
    """bootout returns before the old daemon has exited; a bootstrap of the same label meanwhile fails with EIO."""
    states = iter([(True, 41), (True, 41), (True, None), (False, None)])  # loaded; winding down twice; gone
    calls = []
    monkeypatch.setattr(launchd, "loaded", lambda: next(states, (False, None)))
    monkeypatch.setattr(launchd, "run", lambda argv, timeout=60: (calls.append(argv[1]), Result(0, "", ""))[1])
    monkeypatch.setattr(launchd.time, "sleep", lambda s: calls.append("wait"))
    ran = launchd.install(box.bin / "lflabs-memory")
    assert calls == ["bootout", "wait", "wait", "bootstrap"]
    assert [(a[1], ok, note) for a, ok, note in ran] == [("bootout", True, ""), ("bootstrap", True, "")]


def test_setup_reports_a_bootstrap_launchd_refused(box, capsys):
    box.on("launchctl", ["bootstrap"], 5, "")
    code, out = run_setup()
    shown = capsys.readouterr().out
    assert code != 0, out + shown
    assert "did not start: launchctl exited 5" in shown + out
    assert "see ~/Library/Logs" not in shown + out
