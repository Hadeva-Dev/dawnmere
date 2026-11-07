"""dawnmere uninstall (spec 9.4, Task 10)."""
import json

from lflabs_memory_cli import apps, install_record, layout, prompt, uninstall

CODEX_TOML = '# my codex settings\r\nmodel = "o5"\r\n\r\n[mcp_servers.github]\r\ncommand = "gh-mcp"\r\n'
CURSOR_MCP = '{\n    "mcpServers": {\n        "github": {"command": "gh-mcp"}\n    }\n}\n'
CLAUDE_SETTINGS = '{\n  "theme": "dark",\n  "hooks": {\n    "Stop": [{"hooks": [{"type": "command", "command": "say done"}]}]\n  }\n}\n'
ENGINE = "/Users/x/.local/bin/lflabs-memory"


def seed(home):
    (home / ".codex").mkdir()
    (home / ".codex/config.toml").write_bytes(CODEX_TOML.encode())
    (home / ".cursor").mkdir()
    (home / ".cursor/mcp.json").write_text(CURSOR_MCP)
    (home / ".claude").mkdir()
    (home / ".claude/settings.json").write_text(CLAUDE_SETTINGS)


def fake_setup(home):
    """What setup leaves behind: every app file wired, the record, the agent, the data folder."""
    record = install_record.empty()
    for app in ("codex", "cursor", "claude-code"):
        for p in apps.file_plans(app, ENGINE, home):
            assert p.state == "add", (p.path, p.note)
            apps.apply(p, record)
    record["keychain"] = True
    install_record.save(record)
    layout.plist_path().parent.mkdir(parents=True)
    layout.plist_path().write_text("<plist/>")
    layout.logs_dir().mkdir(parents=True)
    (layout.logs_dir() / "memory.log").write_text("log")
    (layout.data_dir() / "memory.db").write_text("db")
    return record


def test_uninstall_reverses_setup(mac, monkeypatch):
    monkeypatch.setattr(prompt, "yes_no", lambda q, default, assume=None: True)  # "Delete your memory too?" yes
    home = mac.home
    seed(home)
    fake_setup(home)
    assert "lflabs-memory" in (home / ".codex/config.toml").read_text()
    out = []
    assert uninstall.main(out=out.append) == 0
    assert (home / ".codex/config.toml").read_bytes() == CODEX_TOML.encode(), "CRLF file back byte for byte"
    assert (home / ".cursor/mcp.json").read_text() == CURSOR_MCP
    assert (home / ".claude/settings.json").read_text() == CLAUDE_SETTINGS
    assert not (home / ".codex/hooks.json").exists() and not (home / ".cursor/hooks.json").exists()
    assert not layout.plist_path().exists()
    assert not layout.data_dir().exists()
    assert not (home / "Library/Application Support/LF Labs").exists() and not layout.logs_dir().exists()
    assert ["delete-generic-password", "-s", "LF Labs Memory", "-a", "anthropic-api-key"] in mac.calls("security")
    assert ["tool", "uninstall", "lflabs-memory-cli"] in mac.calls("uv")
    backups = list((home / ".codex").glob("config.toml.lflabs-backup-*"))
    assert backups and any(b.name in "\n".join(out) for b in backups), "backups are listed"


def test_uninstall_partial_state(mac):
    """Data folder deleted by hand (so no record), Cursor's entry removed by hand, uv gone: exit 0, all reported."""
    home = mac.home
    seed(home)
    fake_setup(home)
    import shutil
    shutil.rmtree(layout.data_dir())
    cursor = json.loads((home / ".cursor/mcp.json").read_text())
    del cursor["mcpServers"]["lflabs-memory"]
    (home / ".cursor/mcp.json").write_text(json.dumps(cursor))
    mac.remove("uv")
    mac.on("security", ["delete-generic-password"], 44, "")
    out = []
    assert uninstall.main(out=out.append) == 0
    text = "\n".join(out)
    assert "no install record" in text
    assert "no lflabs-memory entry (already removed)" in text
    assert "uv not found" in text and "none in the Keychain" in text
    assert "lflabs-memory" not in (home / ".codex/config.toml").read_text()
    assert "lflabs-memory" not in (home / ".codex/hooks.json").read_text()
    assert "lflabs-memory" not in (home / ".claude/settings.json").read_text()
    assert "say done" in (home / ".claude/settings.json").read_text(), "the user's own hook stays"
    assert "Already gone:" in text
    assert "Your memory          ~/Library/Application Support/LF Labs/Memory: already gone" in text


def test_uninstall_keep_data(mac):
    seed(mac.home)
    fake_setup(mac.home)
    assert uninstall.main(keep_data=True, out=lambda s: None) == 0
    assert (layout.data_dir() / "memory.db").exists()


def test_uninstall_without_install_record(mac):
    """Discovery: our entries come out of files the user changed since; theirs stay."""
    home = mac.home
    seed(home)
    fake_setup(home)
    layout.install_json().unlink()
    toml = (home / ".codex/config.toml").read_text()
    (home / ".codex/config.toml").write_text(toml + '\n[mcp_servers.later]\ncommand = "x"\n')
    assert uninstall.main(out=lambda s: None) == 0
    left = (home / ".codex/config.toml").read_text()
    assert "lflabs-memory" not in left and "[mcp_servers.github]" in left and "[mcp_servers.later]" in left
    assert json.loads((home / ".cursor/mcp.json").read_text()) == {"mcpServers": {"github": {"command": "gh-mcp"}}}


def test_uninstall_leaves_jsonc_alone(mac):
    home = mac.home
    seed(home)
    fake_setup(home)
    layout.install_json().unlink()
    jsonc = '// mine\n{"mcpServers": {"lflabs-memory": {"command": "npx", "args": ["-y", "lflabs-memory-connector@0.1.0"]}}}\n'
    (home / ".cursor/mcp.json").write_text(jsonc)
    out = []
    assert uninstall.main(out=out.append) == 1
    assert (home / ".cursor/mcp.json").read_text() == jsonc
    assert "by hand" in "\n".join(out)


def test_uninstall_asks_before_deleting_memory(mac, monkeypatch):
    """The memory question is always asked; with nobody at a terminal to answer, the memory is kept."""
    seed(mac.home)
    fake_setup(mac.home)
    asked = []
    monkeypatch.setattr(prompt, "yes_no", lambda q, default, assume=None: asked.append((q, default, assume)) or False)
    out = []
    assert uninstall.main(out=out.append) == 0
    assert asked == [("Delete your memory too? It cannot be brought back. Export first with dawnmere export.",
                      False, None)]
    assert (layout.data_dir() / "memory.db").exists()
    assert any(line.startswith("Your memory          kept in") for line in out)
    monkeypatch.undo()
    from lflabs_memory_cli import main as cli
    assert cli.parser().parse_args(["uninstall", "--yes"]).yes  # still accepted, and still asks


def test_uv_in_local_bin_off_path(mac):
    """A new user's uv is the one install.sh put in ~/.local/bin, often not on PATH yet: uninstall still uses it."""
    import shutil
    mac.remove("uv")
    local = mac.home / ".local/bin"
    local.mkdir(parents=True)
    shutil.copy(mac.bin / "security", local / "uv")  # a fake program that logs its argv as "uv"
    assert layout.uv_bin() == str(local / "uv")
    out = []
    uninstall.main(keep_data=True, out=out.append)
    assert ["tool", "uninstall", "lflabs-memory-cli"] in mac.calls("uv")
    assert any(line.startswith("Programs             lflabs-memory-cli and the engine removed") for line in out)
