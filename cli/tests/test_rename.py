"""0.1.10's rename: lflabs-memory (the MCP entry and the plugin) and lflabs (the marketplace) become dawnmere.

An install from 0.1.9 is moved by setup (and the install line, which runs it) and by update; uninstall and doctor know
both names; no app ends up with two entries. Also the dawnmere front doors to the engine's own commands, the plugin's
setup command, and the README's commands."""
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from lflabs_memory_cli import apps, claude_settings, doctor, install_record, layout, main, uninstall, update
from test_doctor import fake_github, wheelset
from test_setup import box, run_setup  # noqa: F401 (box is a fixture)

ROOT = Path(__file__).resolve().parents[2]
ENGINE = "/Users/x/.local/bin/lflabs-memory"
OLD, NEW = layout.OLD_SERVER, layout.SERVER
KEY = "k3y-0123456789"
CODEX_TOML = '# mine\r\nmodel = "o5"\r\n\r\n[mcp_servers.github]\r\ncommand = "gh-mcp"\r\n'


def user_file(app):
    """The app's file as the user had it before 0.1.9's setup, with an entry of their own."""
    if app == "codex":
        return CODEX_TOML
    key = apps.MCP_ONLY[app][3] if app in apps.MCP_ONLY else "mcpServers"
    return json.dumps({"theme": "dark", key: {"github": {"command": "gh-mcp"}}}, indent=4) + "\n"


def mcp_path(home, app):
    return home / {"codex": ".codex/config.toml", "cursor": ".cursor/mcp.json",
                   **{a: v[2] for a, v in apps.MCP_ONLY.items()}}[app]


def setup_019(home, monkeypatch, app, key=None):
    """What 0.1.9's setup wrote: the same plans with the entry under its old name, recorded in install.json."""
    path = mcp_path(home, app)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(user_file(app).encode())
    record = install_record.load() or install_record.empty()
    with monkeypatch.context() as m:
        m.setattr(apps, "SERVER", OLD)
        if app == "codex":
            plan = apps.plan_codex_toml(path, client_key=key)
        else:
            plan = apps.plan_mcp_json(app, app, path, apps.MCP_ONLY[app][3] if app in apps.MCP_ONLY else "mcpServers",
                                      client_key=key)
        assert plan.state == "add" and OLD in plan.new
        apps.apply(plan, record)
    install_record.save(record)
    return path


def servers(path):
    text = path.read_text()
    if path.suffix == ".toml":
        return tomllib.loads(text)["mcp_servers"]
    data = json.loads(text)
    return next(v for k, v in data.items() if isinstance(v, dict) and "github" in v)


@pytest.fixture
def home(mac, tmp_path, monkeypatch):
    monkeypatch.setenv("LFLABS_MEMORY_HOME", str(tmp_path / "data"))
    return mac.home


APPS = ["codex", "cursor", *apps.MCP_ONLY]
KEYED = [("codex", KEY), ("cursor", KEY)]


@pytest.mark.parametrize("app,key", [(a, None) for a in APPS] + KEYED)
@pytest.mark.parametrize("by", ["setup", "update"])
def test_upgrade_from_019_renames_each_apps_entry(home, monkeypatch, app, key, by):
    path = setup_019(home, monkeypatch, app, key)
    before = servers(path)[OLD]
    out = []
    if by == "update":
        update.rename_entries(out.append)
    else:
        record = install_record.load()
        plan = apps.file_plans(app, ENGINE, home)[0]
        assert plan.state == "add" and plan.note.startswith("rename"), plan.note
        apps.apply(plan, record)
        install_record.save(record)
    after = servers(path)
    assert OLD not in after and after[NEW] == before, "one entry, its env (and key) moved with it"
    assert list(after) == ["github", NEW], "the user's entry stays where it was"
    if app == "codex":
        assert f"[mcp_servers.{NEW}.env]".encode() in path.read_bytes() and b"\r\n" in path.read_bytes()
    assert apps.file_plans(app, ENGINE, home)[0].state == "done", "a rerun adds nothing"
    assert apps.plan_rename(app) is None
    assert doctor._old_name(app, doctor.Check("x", "ok", "fine")).state == "ok"
    assert uninstall.main(keep_data=True, out=lambda s: None) == 0
    assert path.read_bytes() == user_file(app).encode(), "uninstall still puts the user's file back byte for byte"


@pytest.mark.parametrize("app", ["codex", "cursor", "gemini"])
def test_both_names_leave_one_entry(home, monkeypatch, app):
    """A 0.1.10 entry added beside an old one (a rerun of an old setup, the engine's connect): the old one goes."""
    path = setup_019(home, monkeypatch, app)
    old_text = path.read_text()
    if app == "codex":
        path.write_text(old_text + "\n" + apps.codex_block())
    else:
        data = json.loads(old_text)
        key = apps.MCP_ONLY[app][3] if app in apps.MCP_ONLY else "mcpServers"
        data[key][NEW] = apps._mcp_entry(app, under=key)
        path.write_text(json.dumps(data))
    plan = apps.file_plans(app, ENGINE, home)[0]
    assert plan.state == "add" and plan.note.startswith("remove the old"), plan.note
    apps.apply(plan, install_record.load())
    after = servers(path)
    assert OLD not in after and apps.ours_server(after[NEW]) and "github" in after


@pytest.mark.parametrize("app", ["codex", "cursor"])
def test_another_tools_entry_under_the_new_name_is_left_alone(home, monkeypatch, app):
    path = setup_019(home, monkeypatch, app)
    if app == "codex":
        path.write_text(path.read_text() + f'\n[mcp_servers.{NEW}]\ncommand = "someone-else"\n')
    else:
        data = json.loads(path.read_text())
        data["mcpServers"][NEW] = {"command": "someone-else"}
        path.write_text(json.dumps(data))
    text = path.read_text()
    plan = apps.file_plans(app, ENGINE, home)[0]
    assert plan.state == "stale" and OLD in plan.note
    update.rename_entries(lambda s: None)
    assert path.read_text() == text


def test_uninstall_without_a_record_takes_out_both_names(home):
    (home / ".codex").mkdir()
    (home / ".cursor").mkdir()
    old_toml = apps.codex_block().replace(f"mcp_servers.{NEW}", f"mcp_servers.{OLD}")
    (home / ".codex/config.toml").write_text(CODEX_TOML.replace("\r\n", "\n") + "\n" + old_toml + "\n" +
                                             apps.codex_block())
    entry = apps._mcp_entry("cursor")
    (home / ".cursor/mcp.json").write_text(json.dumps({"mcpServers": {"github": {"command": "gh-mcp"}, OLD: entry,
                                                                     NEW: entry}}))
    assert uninstall.main(keep_data=True, out=lambda s: None) == 0
    assert tomllib.loads((home / ".codex/config.toml").read_text())["mcp_servers"] == {"github": {"command": "gh-mcp"}}
    assert json.loads((home / ".cursor/mcp.json").read_text()) == {"mcpServers": {"github": {"command": "gh-mcp"}}}


# ---------- Claude Code: the plugin, its marketplace, the fallback's MCP entry ----------

OLD_LIST = "Installed plugins:\n\n  > lflabs-memory@lflabs\n    Version: 0.1.9\n    Scope: user\n"


def plugin_calls(fake):
    return [c for c in fake.calls("claude") if c[:2] in (["plugin", "uninstall"], ["plugin", "install"])
            or c[:3] in (["plugin", "marketplace", "remove"], ["plugin", "marketplace", "add"])]


def test_setup_moves_the_019_plugin(box):  # noqa: F811
    box.on("claude", ["plugin", "list"], 0, OLD_LIST)
    assert run_setup()[0] == 0
    version = __import__("importlib").metadata.version("lflabs-memory-cli")
    assert plugin_calls(box) == [["plugin", "uninstall", "lflabs-memory@lflabs", "--scope", "user"],
                                 ["plugin", "marketplace", "remove", "lflabs"],
                                 ["plugin", "marketplace", "add", f"{layout.REPO}#v{version}", "--scope", "user"],
                                 ["plugin", "install", "dawnmere@dawnmere", "--scope", "user", "-y"]]


def test_setup_moves_the_019_fallback_mcp_entry(box):  # noqa: F811
    box.rules["claude"].insert(0, [["mcp", "get", OLD], 0, f"{OLD}:\n  Args: -y dawnmere-connector@0.1.1\n"])
    box.on("claude", ["plugin", "marketplace", "add"], 1, "")
    box.save()
    assert run_setup()[0] == 0
    calls = box.calls("claude")
    assert ["mcp", "remove", "--scope", "user", OLD] in calls
    assert ["mcp", "add", "--scope", "user", "--transport", "stdio", NEW, "--", "npx", *apps.connector_args()] in calls


def test_update_moves_the_019_plugin(mac, monkeypatch):
    layout.data_dir().mkdir(parents=True)
    mac.add("lflabs-memory")
    (mac.home / ".claude").mkdir()
    mac.on("claude", ["plugin", "list"], 0, OLD_LIST)
    monkeypatch.setattr(update.models, "manifest", lambda: None)
    monkeypatch.setattr(update, "installed_version", lambda: "0.1.10")
    out = []
    assert update.finish("0.1.9", say=out.append, get=fake_github({"0.1.10": wheelset("0.1.10")})) == 0
    assert plugin_calls(mac) == [["plugin", "uninstall", "lflabs-memory@lflabs", "--scope", "user"],
                                 ["plugin", "marketplace", "remove", "lflabs"],
                                 ["plugin", "marketplace", "add", f"{layout.REPO}#v0.1.10", "--scope", "user"],
                                 ["plugin", "install", "dawnmere@dawnmere", "--scope", "user", "-y"]]
    assert "Claude Code's plugin: now v0.1.10 (restart Claude Code to load it)" in out


def test_update_renames_the_019_fallback_mcp_entry(home, mac):
    mac.on("claude", ["mcp", "get", OLD], 0, f"{OLD}:\n  Args: -y dawnmere-connector@0.1.1\n")
    out = []
    update.rename_entries(out.append)
    assert ["mcp", "remove", "--scope", "user", OLD] in mac.calls("claude")
    assert ["mcp", "add", "--scope", "user", "--transport", "stdio", NEW, "--", "npx",
            *apps.connector_args()] in mac.calls("claude")
    assert f"Claude Code: MCP entry {OLD} renamed to {NEW}" in out


def test_update_leaves_another_tools_old_named_mcp_entry(home, mac):
    mac.on("claude", ["mcp", "get", OLD], 0, f"{OLD}:\n  Command: something-else\n")
    update.rename_entries(lambda s: None)
    assert not [c for c in mac.calls("claude") if c[:2] in (["mcp", "remove"], ["mcp", "add"])]


def test_uninstall_takes_out_both_plugin_names(home, mac):
    (mac.home / ".claude").mkdir()
    mac.on("claude", ["plugin", "list"], 0, OLD_LIST + "\n  > dawnmere@dawnmere\n    Version: 0.1.10\n")
    out = []
    assert uninstall.main(keep_data=True, out=out.append) == 0
    calls = plugin_calls(mac)
    for argv in (["plugin", "uninstall", "dawnmere@dawnmere", "--scope", "user"],
                 ["plugin", "marketplace", "remove", "dawnmere"],
                 ["plugin", "uninstall", "lflabs-memory@lflabs", "--scope", "user"],
                 ["plugin", "marketplace", "remove", "lflabs"]):
        assert argv in calls
    text = "\n".join(out)
    assert "plugin dawnmere@dawnmere removed" in text and "plugin lflabs-memory@lflabs removed" in text


def test_settings_entries_of_both_names_come_out():
    data = {"theme": "dark", "enabledPlugins": {"lflabs-memory@lflabs": True, "dawnmere@dawnmere": True},
            "extraKnownMarketplaces": {"lflabs": {}, "dawnmere": {}}}
    assert claude_settings.strip(data) == {"theme": "dark"}


def test_doctor_names_the_old_plugin(home, mac):
    (mac.home / ".claude").mkdir()
    mac.on("claude", ["plugin", "list"], 0, OLD_LIST)
    row = doctor.check_claude()
    assert (row.state, row.note, row.fix) == ("warn", "plugin lflabs-memory 0.1.9 (its old name)",
                                              "run dawnmere setup to rename it")


def test_doctor_names_an_old_app_entry(home, monkeypatch):
    setup_019(home, monkeypatch, "codex")
    (home / ".codex/hooks.json").write_text('{"hooks": {"UserPromptSubmit": [{"hooks": [{"command": "lflabs-memory '
                                            'hook-prompt"}]}]}}')
    row = doctor.check_codex()
    assert row.state == "warn" and "old name lflabs-memory" in row.note and row.fix == "run dawnmere setup to rename it"


# ---------- dawnmere held | trust | forget | restore | search | add ----------

@pytest.mark.parametrize("argv", [["held"], ["held", "--count"], ["trust", "--", "5", "6"], ["forget", "12"],
                                  ["restore", "c3"], ["search", "deploy days", "-k", "3"], ["add", "we ship Fridays"]])
def test_front_doors_run_the_engine_in_place(monkeypatch, argv):
    ran = []
    monkeypatch.setattr(layout, "engine_bin", lambda: "/e/bin/lflabs-memory")
    monkeypatch.setattr(os, "execv", lambda path, args: ran.append((path, args)))
    main.main(argv)
    assert ran == [("/e/bin/lflabs-memory", ["/e/bin/lflabs-memory", *argv])]


def test_front_door_without_an_engine(monkeypatch, capsys):
    monkeypatch.setattr(layout, "engine_bin", lambda: None)
    assert main.main(["held"]) == 1
    assert "The memory engine is not installed" in capsys.readouterr().err


def test_help_lists_the_front_doors():
    text = main.parser().format_help()
    for name in main.FRONT:
        assert re.search(rf"^\s+{name}\s", text, re.M), name


def test_front_door_reaches_the_real_engine():
    """The installed engine answers `dawnmere search --help` itself, naming the command the user typed."""
    r = subprocess.run([sys.executable, "-c", "import sys; from lflabs_memory_cli import main; sys.exit(main.main())",
                        "search", "--help"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and r.stdout.startswith("usage: dawnmere search QUERY"), r.stdout + r.stderr


# ---------- the plugin's setup command, and the README ----------

def install_line():
    m = re.search(r"curl -fsSL (\S+) \| sh", (ROOT / "README.md").read_text())
    return m.group(1)


def test_setup_command_installs_with_the_readme_line_and_no_setup():
    text = (ROOT / "plugin/commands/setup.md").read_text()
    assert text.startswith("---\ndescription: ") and "\n---\n" in text[4:]
    assert f"curl -fsSL {install_line()} | LFLABS_MEMORY_NO_SETUP=1 sh" in text
    assert "`dawnmere setup --dry-run`" in text.replace("~/.local/bin/", "")
    assert "only if the user then says yes" in text.lower()


def test_the_plugins_hooks_never_install_anything():
    script = [line for line in (ROOT / "plugin/scripts/engine").read_text().splitlines() if not line.startswith("#")]
    hooks = (ROOT / "plugin/hooks/hooks.json").read_text() + "\n".join(script)
    for word in ("curl", "install.sh", "dawnmere setup", " setup ", "uv ", "brew", "pip"):
        assert word not in hooks, word


README_FILES = ["README.md", "README.ja.md", "README.zh-CN.md"]


@pytest.mark.parametrize("name", README_FILES)
def test_readme_commands_exist(name):
    text = (ROOT / name).read_text()
    used = set(re.findall(r"\bdawnmere ([a-z][\w-]*)", text)) - {"is", "on", "for", "and", "or", "the", "gives"}
    known = set(main.COMMANDS) | set(main.FRONT)
    assert used and used <= known, used - known
    assert not re.search(r"\blflabs-memory (held|trust|forget|restore|search|add|connect|clients)\b", text)
    assert f"/plugin marketplace add {layout.REPO}" in text
    assert f"/plugin install {claude_settings.PLUGIN_ID}" in text and "/dawnmere:setup" in text
