"""The CLI, the Claude Code plugin and the connector agree: one connector version, the same hooks, one marketplace."""
import json
from pathlib import Path

from lflabs_memory_cli import apps, layout

ROOT = Path(__file__).resolve().parents[2]


def load(rel):
    return json.loads((ROOT / rel).read_text())


def test_connector_version_matches():
    assert load("connector/package.json")["version"] == layout.CONNECTOR_VERSION
    assert load("plugin/.mcp.json")["mcpServers"][layout.SERVER]["args"] == apps.connector_args()


def test_plugin_hooks_match_the_fallback():
    hooks = load("plugin/hooks/hooks.json")["hooks"]
    want = {event: [{"hooks": [{"type": "command", "command": f"{layout.ENGINE} {sub}", "timeout": t}]}]
            for event, sub, t in apps.CLAUDE_HOOKS}
    assert hooks == want
    assert all(apps.ours_command(h["command"]) for groups in hooks.values() for g in groups for h in g["hooks"])


def test_marketplace_names():
    market = load(".claude-plugin/marketplace.json")
    assert market["name"] == layout.MARKETPLACE
    assert market["plugins"][0]["name"] == layout.SERVER == load("plugin/.claude-plugin/plugin.json")["name"]
    assert (ROOT / market["plugins"][0]["source"]).resolve() == ROOT / "plugin"
