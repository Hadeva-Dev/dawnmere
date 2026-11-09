"""The CLI, the Claude Code plugin and the connector agree: one connector version, the same hooks, one marketplace."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

from lflabs_memory_cli import apps, layout

ROOT = Path(__file__).resolve().parents[2]


def load(rel):
    return json.loads((ROOT / rel).read_text())


def test_connector_version_matches():
    assert load("connector/package.json")["version"] == layout.CONNECTOR_VERSION
    assert load("plugin/.mcp.json")["mcpServers"][layout.SERVER]["args"] == apps.connector_args()


def test_marketplace_names():
    market = load(".claude-plugin/marketplace.json")
    assert market["name"] == layout.MARKETPLACE
    assert market["plugins"][0]["name"] == layout.SERVER == load("plugin/.claude-plugin/plugin.json")["name"]
    assert (ROOT / market["plugins"][0]["source"]).resolve() == ROOT / "plugin"


# ---------- the hooks never need PATH ----------

def fake_engine(path):
    """A program that prints its argv and the stdin it got, as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!{sys.executable}\nimport json, sys\nprint(json.dumps([sys.argv[1:], sys.stdin.read()]))\n")
    path.chmod(0o755)
    return path


def hook(tmp_path, sub, env=None):
    """Run the plugin's hook command for sub the way Claude Code does (sh -c, CLAUDE_PLUGIN_ROOT set), from a copy of
    the plugin in a folder with a space, with a PATH that has no engine on it."""
    root = tmp_path / "plugin cache" / "lflabs-memory"
    if not root.exists():
        shutil.copytree(ROOT / "plugin", root)
    cmd = next(h["command"] for groups in load("plugin/hooks/hooks.json")["hooks"].values() for g in groups
               for h in g["hooks"] if h["command"].endswith(" " + sub))
    base = {"HOME": str(tmp_path / "home"), "PATH": "/usr/bin:/bin", "CLAUDE_PLUGIN_ROOT": str(root)}
    return subprocess.run(["/bin/sh", "-c", cmd], input='{"prompt": "hi"}', capture_output=True, text=True,
                          env={**base, **(env or {})}, timeout=30)


def test_plugin_hooks_run_the_launcher():
    """Not a bare lflabs-memory (PATH): /bin/sh and the plugin's own launcher, its path quoted."""
    hooks = load("plugin/hooks/hooks.json")["hooks"]
    launcher = '/bin/sh "${CLAUDE_PLUGIN_ROOT}/scripts/engine"'
    want = {event: [{"hooks": [{"type": "command", "command": f"{launcher} {sub}", "timeout": t}]}]
            for event, sub, t in apps.CLAUDE_HOOKS}
    assert hooks == want


def test_hook_runs_the_engine_setup_recorded(tmp_path):
    eng = fake_engine(tmp_path / "Somewhere Else/bin/lflabs-memory")
    record = tmp_path / "home/Library/Application Support/LF Labs/Memory/engine-path"
    record.parent.mkdir(parents=True)
    record.write_text(f"{eng}\n")
    for _, sub, _ in apps.CLAUDE_HOOKS:
        r = hook(tmp_path, sub)
        assert r.returncode == 0 and json.loads(r.stdout) == [[sub], '{"prompt": "hi"}'], r.stderr


def test_hook_falls_back_to_uvs_bin_folder(tmp_path):
    fake_engine(tmp_path / "home/.local/bin/lflabs-memory")
    assert json.loads(hook(tmp_path, "hook-prompt").stdout)[0] == ["hook-prompt"]
    fake_engine(tmp_path / "tools bin/lflabs-memory")
    (tmp_path / "home/.local/bin/lflabs-memory").unlink()
    r = hook(tmp_path, "hook-prompt", {"UV_TOOL_BIN_DIR": str(tmp_path / "tools bin")})
    assert json.loads(r.stdout)[0] == ["hook-prompt"]


def test_hook_without_an_engine_is_quiet(tmp_path):
    """A broken install never blocks a prompt: exit 0, nothing on stdout or stderr."""
    r = hook(tmp_path, "hook-prompt")
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")


def test_doctor_finds_what_the_launcher_finds(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("LFLABS_MEMORY_HOME", raising=False)
    monkeypatch.delenv("UV_TOOL_BIN_DIR", raising=False)
    monkeypatch.delenv("XDG_BIN_HOME", raising=False)
    assert apps.hook_engine() is None
    eng = fake_engine(tmp_path / "home/.local/bin/lflabs-memory")
    assert apps.hook_engine() == str(eng)
