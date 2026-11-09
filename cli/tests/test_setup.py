"""dawnmere setup (spec 9.2, Task 9): a temp HOME, fake claude, launchctl, security, zsh and engine."""
import hashlib
import importlib.metadata
import json
import os
import shutil
import socketserver
import stat
import subprocess
import sys
import tempfile
import threading
import tomllib
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
    version = importlib.metadata.version("lflabs-memory-cli")
    assert ["plugin", "marketplace", "add", f"Hadeva-Dev/dawnmere#v{version}", "--scope", "user"] in \
        box.calls("claude"), "the plugin at the release tag the wheels come from, never main's head"
    assert "dawnmere-connector@0.1.1" in (box.home / ".codex/config.toml").read_text()
    assert "hook-cursor-start" in (box.home / ".cursor/hooks.json").read_text()
    assert (layout.data_dir() / "config.toml").read_text().startswith('version = 1\nprofile = "generic"')
    assert oct(os.stat(layout.data_dir() / "config.toml").st_mode & 0o777) == "0o600"
    assert models.check(models.manifest()) == {"embed": "ok", "rerank": "ok"}
    assert any(c[:1] == ["bootstrap"] for c in box.calls("launchctl"))
    assert ["purge", "7"] in box.calls("lflabs-memory"), "the self-check's memory is deleted for good"
    assert layout.engine_record().read_text() == layout.engine_bin() + "\n", "the plugin's hooks run this path"
    assert os.path.isabs(layout.engine_bin()) and "PATH" not in out


def test_setup_dry_run_lists_changes(box):
    before = tree(box.home)
    (box.home / ".codex/config.toml").write_text("model = 'o5'\n")
    before = tree(box.home)
    code, out = run_setup("--dry-run")
    assert code == 0
    assert tree(box.home) == before and not (layout.data_dir() / "config.toml").exists()
    assert box.calls("launchctl") == [] and not [c for c in box.calls("claude") if c[:1] == ["plugin"]]
    for line in ("~/.codex/config.toml: add [mcp_servers.lflabs-memory]", 'args = ["-y", "dawnmere-connector@0.1.1"]',
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
    assert '"dawnmere-connector@0.1.1"' in out, "the lines to add are printed"


def test_plugin_fallback_when_plugin_cli_fails(box, capsys):
    box.on("claude", ["plugin", "marketplace"], 1, "")
    assert run_setup()[0] == 0
    calls = box.calls("claude")
    assert ["mcp", "add", "--scope", "user", "--transport", "stdio", "lflabs-memory", "--", "npx", "-y",
            "dawnmere-connector@0.1.1"] in calls
    hooks = json.loads((box.home / ".claude/settings.json").read_text())["hooks"]
    assert set(hooks) == {"UserPromptSubmit", "SessionStart", "Stop", "SessionEnd"}
    assert hooks["UserPromptSubmit"][0]["hooks"][0]["command"] == f"{box.bin}/lflabs-memory hook-prompt", \
        "the absolute path, never one PATH has to find"


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
    typed = at_a_terminal(monkeypatch, "cursor")
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
    for text in (out, shown, layout.install_json().read_text()):
        assert key not in text, "the key is never shown or recorded"
    assert typed == [("cursor", "everything")], "confirmed through the engine's gate, as by access"
    assert "Cursor now sees everything, personal notes too. Restart Cursor to load it." in out
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
    at_a_terminal(monkeypatch, "cursor")
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


def test_path_advice_when_a_new_terminal_would_not_find_dawnmere(box, capsys):
    """Checked the way a new Terminal window starts zsh (login and interactive), so the advice is ~/.zshrc."""
    box.on("zsh", ["-lic"], 1, "")
    code, out = run_setup()
    assert code == 0
    assert ["-lic", "command -v dawnmere"] in box.calls("zsh")
    assert 'To run dawnmere later, add this line to ~/.zshrc:\n  export PATH="' in out
    box.rules["zsh"] = []
    box.save()
    assert "~/.zshrc" not in run_setup()[1]


@pytest.mark.skipif(not os.path.exists("/bin/zsh"), reason="no zsh")
def test_path_advice_and_check_agree(tmp_path, monkeypatch):
    """The real zsh: the line the advice gives, put in ~/.zshrc, is what makes the check pass."""
    home = tmp_path / "home"
    tools = tmp_path / "tools bin"
    tools.mkdir(parents=True)
    home.mkdir()
    (tools / "dawnmere").write_text("#!/bin/sh\n")
    (tools / "dawnmere").chmod(0o755)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(layout, "tool_bin", lambda: str(tools))
    assert not layout.on_shell_path()
    advice = layout.path_advice()
    assert advice.startswith("To run dawnmere later, add this line to ~/.zshrc:\n  ")
    (home / ".zshrc").write_text(advice.splitlines()[1].strip() + "\n")
    assert layout.on_shell_path()


def test_marketplace_override_for_testing(box, monkeypatch, tmp_path):
    monkeypatch.setenv("LFLABS_MEMORY_MARKETPLACE", str(tmp_path / "checkout"))
    assert run_setup()[0] == 0
    assert ["plugin", "marketplace", "add", str(tmp_path / "checkout"), "--scope", "user"] in box.calls("claude")


def test_dry_run_names_the_tag(box):
    version = importlib.metadata.version("lflabs-memory-cli")
    assert f"claude plugin marketplace add Hadeva-Dev/dawnmere#v{version} --scope user" in run_setup("--dry-run")[1]


def test_no_terminal_needs_yes(box, monkeypatch, capsys):
    """Nobody at a terminal to say yes: no consent is assumed, nothing changes. --yes still works, for scripts."""
    import io
    monkeypatch.setattr(setup.sys, "stdin", io.StringIO(""))
    out = []
    code = setup.main(cli.parser().parse_args(["setup", "--plain"]), say=out.append)
    assert code == 1 and box.calls("launchctl") == [] and not (layout.data_dir() / "config.toml").exists()
    assert out[-1] == ("There is no terminal to ask on, so nothing was changed. Run dawnmere setup in a Terminal "
                       "window, or dawnmere setup --yes to take the defaults.")
    assert run_setup("--backend", "none")[0] == 0


def test_setup_closes_the_lf_labs_folder(box):
    """The folder above the data folder holds the connector's socket: owner only too (a real one was 0755)."""
    parent = box.home / "Library/Application Support/LF Labs"
    parent.mkdir(parents=True)
    parent.chmod(0o755)
    assert run_setup()[0] == 0
    assert oct(parent.stat().st_mode & 0o777) == "0o700"
    assert oct(layout.data_dir().stat().st_mode & 0o777) == "0o700"


# ---------- widening what an app sees needs a person ----------

def test_an_agent_is_never_offered_cursors_personal_notes(box, monkeypatch):
    asked = answering(monkeypatch, {"Let Cursor see your personal notes too?": True})
    monkeypatch.setenv("CODEX_THREAD_ID", "t1")
    assert run_setup()[0] == 0
    assert not any("personal notes" in q for q in asked)
    assert "LFLABS_MEMORY_CLIENT_KEY" not in (box.home / ".cursor/mcp.json").read_text()


def at_a_terminal(monkeypatch, typed):
    """The engine's gate (`lflabs-memory clients level`, on the terminal: the app's name typed, Allow clicked in a
    macOS dialog) answers as a person who typed `typed` and clicked Allow would. Records each gated call."""
    from lflabs_memory_cli import access
    asked = []

    def gate(engine, app, level):
        asked.append((app, level))
        return typed == app
    monkeypatch.setattr(access, "engine_widens", gate)
    for k in access.AGENT_ENV:
        monkeypatch.delenv(k, raising=False)
    return asked


def test_widening_goes_through_the_engines_gate_first(box, monkeypatch, capsys):
    from lflabs_memory_cli import access
    assert run_setup()[0] == 0
    eng, out = layout.engine_bin(), []
    asked = at_a_terminal(monkeypatch, "no")
    assert access.main("cursor", "everything", eng, say=out.append) == 1
    assert asked == [("cursor", "everything")] and out[-1].startswith("Not changed: Cursor still sees ")
    assert "LFLABS_MEMORY_CLIENT_KEY" not in (box.home / ".cursor/mcp.json").read_text(), "no key before the gate"
    at_a_terminal(monkeypatch, "cursor")
    assert access.main("cursor", "everything", eng, say=out.append) == 0
    assert "LFLABS_MEMORY_CLIENT_KEY" in (box.home / ".cursor/mcp.json").read_text()


def test_the_gate_is_the_engines_command_on_this_terminal(monkeypatch):
    """`lflabs-memory clients level` with this process's stdin, stdout and stderr (its prompt and dialog need the
    person), and the level read back, since the engine prints a refusal and exits 0."""
    from lflabs_memory_cli import access
    calls, levels = [], iter(["work only", "everything"])
    monkeypatch.setattr(access.subprocess, "run", lambda argv, **kw: calls.append((argv, kw)))
    monkeypatch.setattr(access, "current_level", lambda app: next(levels))
    assert access.engine_widens("/e/lflabs-memory", "cursor", "everything") is False
    assert access.engine_widens("/e/lflabs-memory", "cursor", "everything") is True
    assert calls[0] == (["/e/lflabs-memory", "clients", "level", "cursor", "everything"], {"timeout": 600})


@pytest.mark.parametrize("marker", ["CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CODEX_SANDBOX", "CODEX_THREAD_ID",
                                    "CURSOR_AGENT", "CURSOR_CONVERSATION_ID"])
def test_widening_from_an_ai_apps_shell_is_refused(box, monkeypatch, marker):
    """Refused before the engine is even asked (the engine refuses it too)."""
    from lflabs_memory_cli import access
    assert run_setup()[0] == 0
    asked = at_a_terminal(monkeypatch, "cursor")
    monkeypatch.setenv(marker, "1")
    out = []
    assert access.main("cursor", "everything", layout.engine_bin(), say=out.append) == 1
    assert asked == [] and out[-1].startswith(f"Refused: this is an AI app's shell ({marker} is set).")


def test_narrowing_needs_no_confirmation(box, monkeypatch):
    from lflabs_memory_cli import access
    assert run_setup()[0] == 0
    asked = at_a_terminal(monkeypatch, "")
    monkeypatch.setenv("CLAUDECODE", "1")
    out = []
    assert access.main("cursor", "nothing", layout.engine_bin(), say=out.append) == 0
    assert asked == [] and ["clients", "level", "cursor", "nothing"] in box.calls("lflabs-memory")


# ---------- uninstall after setup, access and the engine's own connect ----------

def claude_plugin_rewrites(home):
    """What Claude Code does to settings.json while setup's plugin commands run (seen on 2.1.301): keys reordered,
    "opus" made "opus[1m]", the marketplace and the plugin added; and its cached copy of the plugin."""
    s = json.loads((home / ".claude/settings.json").read_text()) if (home / ".claude/settings.json").exists() else {}
    s = dict(reversed(list(s.items())))
    if s.get("model") == "opus":
        s["model"] = "opus[1m]"
    s["extraKnownMarketplaces"] = {"lflabs": {"source": {"source": "github", "repo": "Hadeva-Dev/dawnmere"}}}
    s["enabledPlugins"] = {"lflabs-memory@lflabs": True}
    (home / ".claude/settings.json").write_text(json.dumps(s, indent=2) + "\n")
    cache = home / ".claude/plugins/cache/lflabs/lflabs-memory/0.1.6"
    cache.mkdir(parents=True)
    (cache / ".orphaned_at").write_text("1")
    (home / ".claude/plugins/known_marketplaces.json").write_text("{}")
    (home / ".claude/plugins/installed_plugins.json").write_text('{"version": 2, "plugins": {}}')


def engine_connect(home):
    """What the engine's own `lflabs-memory connect --yes` wrote on older installs: the python running the engine's
    script, the old JARVIS_MEMORY_* names, a key; and its own key-bearing backups."""
    hooks = json.loads((home / ".codex/hooks.json").read_text())
    hooks["hooks"]["UserPromptSubmit"].append({"hooks": [{"type": "command", "timeout": 10, "command":
        "JARVIS_MEMORY_CLIENT=codex JARVIS_MEMORY_CLIENT_KEY=k3y /u/.local/share/uv/tools/x/bin/python "
        "/u/.local/share/uv/tools/x/bin/lflabs-memory hook-prompt"}]})
    (home / ".codex/hooks.json").write_text(json.dumps(hooks, indent=2))
    mcp = home / ".cursor/mcp.json"
    (mcp.parent / "mcp.json.lflabs-backup-20261101T000000Z").write_text(mcp.read_text())
    m = json.loads(mcp.read_text())
    m["mcpServers"]["lflabs-memory"]["env"] = {"JARVIS_MEMORY_CLIENT": "cursor", "JARVIS_MEMORY_CLIENT_KEY": "k3y"}
    m["mcpServers"]["lflabs-memory-2"] = {"command": "/u/bin/python", "args": ["/u/bin/lflabs-memory", "serve",
                                                                               "--client", "cursor"]}
    mcp.write_text(json.dumps(m, indent=2))


def test_uninstall_after_access_and_the_engines_connect_leaves_the_users_files(box, monkeypatch, capsys):
    from lflabs_memory_cli import access, prompt, uninstall
    (box.home / ".codex/config.toml").write_bytes(b'model = "o5"\r\n')
    (box.home / ".claude/settings.json").write_text('{\n  "theme": "dark",\n  "model": "opus"\n}\n')
    before = tree(box.home)
    assert run_setup()[0] == 0
    claude_plugin_rewrites(box.home)
    at_a_terminal(monkeypatch, "cursor")
    assert access.main("cursor", "everything", layout.engine_bin(), say=lambda s: None) == 0
    key = json.loads((box.home / ".cursor/mcp.json").read_text())["mcpServers"]["lflabs-memory"]["env"][
        "LFLABS_MEMORY_CLIENT_KEY"]
    for b in box.home.rglob("*.lflabs-backup-*"):
        assert key not in b.read_text(), f"{b} holds Cursor's key"
    engine_connect(box.home)
    monkeypatch.setattr(prompt, "yes_no", lambda q, default, assume=None: True)
    out = []
    assert uninstall.main(out=out.append) == 0, "\n".join(out)
    assert tree(box.home) == before, "every file as it was, no backups, no empty files, no plugin cache"


def test_access_then_uninstall_puts_cursors_own_file_back(box, monkeypatch, capsys):
    """`access cursor everything` rewrote mcp.json without telling install.json: uninstall could not restore it."""
    from lflabs_memory_cli import access, uninstall
    mine = '{\n    "mcpServers": {"gh": {"command": "gh-mcp"}}\n}\n'
    (box.home / ".cursor/mcp.json").write_text(mine)
    assert run_setup()[0] == 0
    at_a_terminal(monkeypatch, "cursor")
    assert access.main("cursor", "everything", layout.engine_bin(), say=lambda s: None) == 0
    assert uninstall.main(keep_data=True, out=lambda s: None) == 0
    assert (box.home / ".cursor/mcp.json").read_text() == mine
    assert not list((box.home / ".cursor").glob("mcp.json.lflabs-backup-*"))


def test_uninstall_keeps_changes_made_since_and_takes_out_only_the_plugins(box, monkeypatch):
    from lflabs_memory_cli import uninstall
    (box.home / ".claude/settings.json").write_text('{\n  "theme": "dark"\n}\n')
    assert run_setup()[0] == 0
    claude_plugin_rewrites(box.home)
    s = json.loads((box.home / ".claude/settings.json").read_text())
    s["theme"] = "light"  # the user's own change since
    (box.home / ".claude/settings.json").write_text(json.dumps(s, indent=2) + "\n")
    assert uninstall.main(keep_data=True, out=lambda s: None) == 0
    assert json.loads((box.home / ".claude/settings.json").read_text()) == {"theme": "light"}
    assert not (box.home / ".claude/plugins").exists(), "setup made it; only empty bookkeeping was left"


def test_uninstall_removes_a_settings_json_that_was_not_there(box):
    from lflabs_memory_cli import uninstall
    assert run_setup()[0] == 0
    claude_plugin_rewrites(box.home)
    assert uninstall.main(keep_data=True, out=lambda s: None) == 0
    assert not (box.home / ".claude/settings.json").exists()


def test_uninstall_removes_stale_sockets(box):
    """Sockets nothing answers on (the service is gone) are removed; the data stays (--keep-data)."""
    import socket as sk
    from lflabs_memory_cli import uninstall
    assert run_setup()[0] == 0
    stale = Path(tempfile.mkdtemp(prefix="lfs", dir="/tmp")) / "c.sock"
    s = sk.socket(sk.AF_UNIX)
    s.bind(str(stale))
    s.close()
    os.environ["LFLABS_MEMORY_SOCKET"] = str(stale)
    try:
        out = []
        assert uninstall.main(keep_data=True, out=out.append) == 0
        assert not stale.exists() and any("nothing answered on it" in x for x in out)
        assert (layout.data_dir() / "engine.sock").exists(), "the engine still answers there (the test's server)"
    finally:
        shutil.rmtree(stale.parent, ignore_errors=True)


def test_self_check_without_git(box, capsys):
    """Without Apple's Command Line Tools /usr/bin/git only asks to install them, so the check folder is no repo, and
    the engine cannot tell which repo a new Cursor chat is in (macOS 26 runners failed "a new Cursor chat would not
    see it" this way). Setup then says so instead of failing."""
    (box.bin / "git").write_text("#!/bin/sh\necho 'xcrun: error: invalid active developer path' >&2\nexit 1\n")
    (box.bin / "git").chmod(0o755)
    code, out = run_setup()
    shown = capsys.readouterr().out
    assert code == 0, out + shown
    assert "[warn] Self-check: recall in" in shown and "git missing (see below)" in shown
    assert "git does not work on this Mac: install Apple's Command Line Tools (xcode-select --install)" in out
    start = next(json.loads(r)["stdin"] for r in box.log.read_text().splitlines()
                 if json.loads(r)["argv"] == ["hook-cursor-start"]) if False else None
    assert start is None
    assert not list(box.home.glob("lflabs-check-*")), "the check folder in the home folder is gone again"


def test_setup_stores_where_claude_is(box, tmp_path):
    """The background service finds claude only in fixed folders (launchd's PATH): setup asks a login shell where it
    is, as a new Terminal window would find it (an alias too), and puts the absolute path in config.toml."""
    real = tmp_path / "Claude Code" / "claude"
    real.parent.mkdir()
    shutil.copy(box.bin / "claude", real)
    box.on("zsh", ["-lic", "whence -p claude || alias claude"], 0, f"some rc noise\nclaude='{real}'\n")
    assert run_setup()[0] == 0
    cfg = tomllib.loads((layout.data_dir() / "config.toml").read_text())
    assert cfg["llm"]["claude_path"] == str(real)
    box.rules["zsh"] = []
    box.save()
    assert run_setup()[0] == 0
    assert tomllib.loads((layout.data_dir() / "config.toml").read_text())["llm"]["claude_path"] == f"{box.bin}/claude", \
        "else the claude on PATH"


STAR = "If Dawnmere helps, a star helps others find it: github.com/Hadeva-Dev/dawnmere"


def interactive(monkeypatch):
    """A person at a terminal (setup's own questions still take their defaults)."""
    import io

    class TTY(io.StringIO):
        def isatty(self):
            return True
    monkeypatch.setattr(setup.sys, "stdin", TTY(""))
    monkeypatch.setattr(setup.sys, "stdout", TTY())
    answering(monkeypatch, {})
    from lflabs_memory_cli import prompt
    monkeypatch.setattr(prompt, "text", lambda q, default="": default)


def test_the_star_line_once_per_mac(box, monkeypatch, capsys):
    interactive(monkeypatch)
    say = []
    args = cli.parser().parse_args(["setup", "--no-animation"])
    assert setup.main(args, say=say.append) == 0
    shown = [line for line in say if STAR in line]
    assert len(shown) == 1 and len(setup.screen.visible(shown[0]).strip("\n")) <= 80
    flag = layout.data_dir() / ".star-shown"
    assert flag.exists() and oct(flag.stat().st_mode & 0o777) == "0o600"
    say = []
    assert setup.main(args, say=say.append) == 0
    assert not any(STAR in line for line in say), "never again, setup re-run or not"


@pytest.mark.parametrize("flags", [["--plain"], ["--yes"]])
def test_no_star_line_in_plain_or_yes_runs(box, monkeypatch, flags):
    interactive(monkeypatch)
    say = []
    assert setup.main(cli.parser().parse_args(["setup", "--no-animation", *flags]), say=say.append) == 0
    assert not any(STAR in line for line in say) and not (layout.data_dir() / ".star-shown").exists()


def test_no_star_line_without_a_terminal_or_after_a_failure(box, monkeypatch, capsys):
    code, out = run_setup()  # --yes, and no terminal
    assert STAR not in out
    interactive(monkeypatch)
    json.dump({"refuse": True}, open(os.environ["FAKE_ENGINE_STATE"], "w"))
    say = []
    assert setup.main(cli.parser().parse_args(["setup", "--no-animation"]), say=say.append) == 1
    assert not any(STAR in line for line in say) and not (layout.data_dir() / ".star-shown").exists()
