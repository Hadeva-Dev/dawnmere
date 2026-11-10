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
    assert "[mcp_servers.dawnmere]" in (home / ".codex/config.toml").read_text()
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
    assert not list(home.rglob("*.lflabs-backup-*")), "every file put back: its backups go too"


def test_uninstall_under_homebrew_leaves_the_programs_to_brew(mac, monkeypatch):
    """Its own steps as ever, then the formula's command: no uv tool uninstall, no word about uv."""
    monkeypatch.setattr(layout, "homebrew", lambda: True)
    home = mac.home
    seed(home)
    fake_setup(home)
    local = home / ".local/bin"
    local.mkdir(parents=True)
    import shutil
    shutil.copy(mac.bin / "uv", local / "uv")  # the user's own uv, from another tool's installer
    out = []
    assert uninstall.main(out=out.append) == 0
    assert (home / ".cursor/mcp.json").read_text() == CURSOR_MCP and not layout.plist_path().exists()
    assert mac.calls("uv") == []
    assert out[-2:] == ["The dawnmere command itself came from Homebrew. To remove it:", "  brew uninstall dawnmere"]
    assert not any("uv" in line.split() or "uv not found" in line for line in out)


def test_uninstall_partial_state(mac):
    """Data folder deleted by hand (so no record), Cursor's entry removed by hand, uv gone: exit 0, all reported."""
    home = mac.home
    seed(home)
    fake_setup(home)
    import shutil
    shutil.rmtree(layout.data_dir())
    cursor = json.loads((home / ".cursor/mcp.json").read_text())
    del cursor["mcpServers"]["dawnmere"]
    (home / ".cursor/mcp.json").write_text(json.dumps(cursor))
    mac.remove("uv")
    mac.on("security", ["delete-generic-password"], 44, "")
    out = []
    assert uninstall.main(out=out.append) == 0
    text = "\n".join(out)
    assert "no install record" in text
    assert "no dawnmere entry (already removed)" in text
    assert "uv not found" in text and "none in the Keychain" in text
    assert "mcp_servers.dawnmere" not in (home / ".codex/config.toml").read_text()
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
    assert "mcp_servers.dawnmere" not in left and "[mcp_servers.github]" in left and "[mcp_servers.later]" in left
    assert json.loads((home / ".cursor/mcp.json").read_text()) == {"mcpServers": {"github": {"command": "gh-mcp"}}}


def test_uninstall_leaves_jsonc_alone(mac):
    home = mac.home
    seed(home)
    fake_setup(home)
    layout.install_json().unlink()
    jsonc = '// mine\n{"mcpServers": {"lflabs-memory": {"command": "npx", "args": ["-y", "dawnmere-connector@0.1.0"]}}}\n'
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


def test_uv_is_said_to_stay(mac):
    """The uv install.sh put in ~/.local/bin stays (other tools may use it): the end says how to remove it and its
    Python, never its tool folder. A uv from anywhere else (Homebrew) is not ours to mention."""
    import shutil
    seed(mac.home)
    fake_setup(mac.home)
    out = []
    assert uninstall.main(keep_data=True, out=out.append) == 0
    assert not any("uv cache clean" in line for line in out), "a uv on PATH that is not the installer's"
    local = mac.home / ".local/bin"
    local.mkdir(parents=True)
    shutil.copy(mac.bin / "uv", local / "uv")
    out = []
    uninstall.main(keep_data=True, out=out.append)
    assert out[-2:] == ["uv and the Python it downloaded stay on this Mac (other tools may use them). If nothing else "
                        "needs them:",
                        '  ~/.local/bin/uv cache clean && rm -rf "$(~/.local/bin/uv python dir)" ~/.local/bin/uv '
                        "~/.local/bin/uvx"]
    assert not any("tool dir" in line for line in out)


def test_engine_written_entries_are_ours():
    """The engine's own connect wrote a python running the engine's script, and older engines JARVIS_MEMORY_* names."""
    assert apps.ours_command("JARVIS_MEMORY_CLIENT=codex JARVIS_MEMORY_CLIENT_KEY=k /u/bin/python3.12 "
                             "/u/bin/lflabs-memory hook-prompt")
    assert apps.ours_command("env LFLABS_MEMORY_CLIENT=cursor /u/bin/lflabs-memory hook-cursor-start")
    assert apps.ours_server({"command": "/u/bin/python", "args": ["/u/bin/lflabs-memory", "serve", "--client", "x"]})
    assert apps.ours_server({"command": "lflabs-memory", "args": ["serve"]})
    assert not apps.ours_command("/u/bin/python /u/bin/other hook-prompt")
    assert not apps.ours_server({"command": "/u/bin/python", "args": ["/u/bin/lflabs-memory-ish", "serve"]})
    assert not apps.ours_server({"command": "node", "args": ["server.js"]})


def test_a_file_setup_created_goes_when_only_empty_structure_is_left(mac):
    """A created mcp.json someone (the engine's connect) rewrote since: our entry out, nothing but {"mcpServers": {}}
    left, so the file goes."""
    home = mac.home
    (home / ".cursor").mkdir()
    record = install_record.empty()
    for p in apps.file_plans("cursor", ENGINE, home):
        apps.apply(p, record)
    install_record.save(record)
    data = json.loads((home / ".cursor/mcp.json").read_text())
    data["mcpServers"]["dawnmere"]["env"] = {"JARVIS_MEMORY_CLIENT": "cursor"}
    (home / ".cursor/mcp.json").write_text(json.dumps(data))
    assert uninstall.main(keep_data=True, out=lambda s: None) == 0
    assert not (home / ".cursor/mcp.json").exists() and not (home / ".cursor/hooks.json").exists()


def zprofile(home, before, was):
    line = 'export PATH="/u/.local/bin:$PATH"  # added by the Dawnmere installer'
    add = ("\n" if before and not before.endswith("\n") else "") + line
    if before is not None:
        (home / ".zprofile").write_text(before)
    with open(home / ".zprofile", "a") as f:
        f.write(add + "\n")
    layout.data_dir().mkdir(parents=True, exist_ok=True)
    (layout.data_dir() / "zprofile-line").write_text(f"{was}\n{add}\n")


def test_uninstall_takes_out_the_installers_zprofile_line(mac):
    mine = 'eval "$(/opt/homebrew/bin/brew shellenv)"'
    zprofile(mac.home, mine, "existing")
    (mac.home / ".zprofile").write_text((mac.home / ".zprofile").read_text() + "alias ll='ls -l'\n")  # added since
    out = []
    assert uninstall.main(keep_data=True, out=out.append) == 0
    assert (mac.home / ".zprofile").read_text() == mine + "\nalias ll='ls -l'\n", "exactly our line, nothing else"
    assert any("~/.zprofile: the installer's PATH line taken out" in x for x in out)
    assert not (layout.data_dir() / "zprofile-line").exists()


def test_uninstall_removes_a_zprofile_the_installer_made(mac):
    zprofile(mac.home, None, "created")
    assert uninstall.main(keep_data=True, out=lambda s: None) == 0
    assert not (mac.home / ".zprofile").exists()
