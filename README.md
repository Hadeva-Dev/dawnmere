# Dawnmere

One long-term memory on your Mac, shared by your AI apps. Tell Claude Code a project decision on Monday, and Codex
and Cursor know it on Tuesday. The memory is one file on your Mac; search runs on your Mac with small local models.

Early beta. This repo holds the installer, the `dawnmere` command, the Claude Code plugin and the
[connector](connector/) your apps run to reach the memory. The memory itself is the
[engine](https://github.com/Hadeva-Dev/lflabs-memory-engine), which the installer sets up for you.

## Install

```bash
curl -fsSL https://github.com/Hadeva-Dev/dawnmere/releases/latest/download/install.sh | sh
```

You need:

- a Mac with Apple silicon (M1 or later) and macOS 14 or later, with 1 GB of free disk space;
- Node.js 18 or later, for your apps to use memory's tools (recall, remember, forget);
- Claude Code 2.1.301 or later, if your Claude plan is to do the background reading (optional).

The installer downloads [uv](https://github.com/astral-sh/uv) if you do not have it, then the `dawnmere` command and the
engine. It checks every download against the sha256 written into it, and installs nothing if one differs. Then it
starts `dawnmere setup`.

If `dawnmere` is not found afterwards, add `~/.local/bin` to your PATH, as the installer says:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
```

## What setup does

`dawnmere setup` first shows what it does and what it changes, and asks before changing anything. Then it asks:

1. what your AI apps should call you;
2. whether to use your Claude plan for background reading (or an Anthropic API key instead, kept in your Keychain);
3. whether Cursor may see your personal notes (no, unless you say yes);
4. whether to import the notes Claude Code already keeps in `~/.claude/projects/*/memory`.

Then it shows each step as it runs:

| step | what happens |
| --- | --- |
| Claude Code | checks that `claude` is there and logged in |
| Search models | downloads the search models (about 310 MB) and checks each file's sha256 |
| Memory service | starts a background service (a LaunchAgent) that keeps search fast |
| Your apps | connects Claude Code, Codex and Cursor, if they are installed (below) |
| Your notes | imports your Claude Code notes |
| Self-check | saves a test memory, finds it the way Codex and Cursor would, then deletes it |

It ends with "Dawnmere is on." and a line to try. Every file setup changes is copied first, next to it
(`<file>.lflabs-backup-<time>`), and recorded so `dawnmere uninstall` can put it back. You can run setup again, for example to choose a model later.
`dawnmere setup --dry-run` prints every change it would make and makes none.

Without a model (`dawnmere setup --backend none`), recall and remember still work; automatic saving is off.

## Your apps

Setup connects these when it finds them:

- **Claude Code**: installs the `lflabs-memory` plugin from this repo, which gives Claude Code memory's tools and four
  hooks: recall into each prompt, and saving after a session goes quiet. If the plugin cannot be installed, setup adds
  the same tools with `claude mcp add` and the hooks to `~/.claude/settings.json`.
- **Codex**: adds `[mcp_servers.lflabs-memory]` to `~/.codex/config.toml` and a prompt hook to `~/.codex/hooks.json`.
  Type `/hooks` once in Codex to trust the hook.
- **Cursor**: adds `lflabs-memory` to `~/.cursor/mcp.json` and a session-start hook to `~/.cursor/hooks.json`. Restart
  Cursor. Cursor sees work notes only; `dawnmere access cursor everything` lets it see your personal notes too, and
  `dawnmere access cursor work` takes that back.
- **Claude Desktop** and other apps with MCP settings: setup does not connect them. Add the connector by hand, for
  Claude Desktop in `~/Library/Application Support/Claude/claude_desktop_config.json`:

  ```json
  {
    "mcpServers": {
      "lflabs-memory": {
        "command": "npx",
        "args": ["-y", "lflabs-memory-connector@0.1.0"]
      }
    }
  }
  ```

  The [connector's README](connector/README.md) has the lines for other apps.

## Commands

| command | what it does |
| --- | --- |
| `dawnmere setup` | connect your apps to one memory on this Mac |
| `dawnmere doctor` | check that everything works, one line per check, and say what to do about each problem |
| `dawnmere export` | save your memory to `~/Downloads/dawnmere-export-<date>.json` (`--format md` for Markdown) |
| `dawnmere import FILE` | add the memories from an export file, skipping any already there |
| `dawnmere access APP [LEVEL]` | show or change what an app may see: `everything`, `work` or `nothing` |
| `dawnmere update` | install the newest release, checked against its checksums |
| `dawnmere uninstall` | remove everything setup added |

`dawnmere doctor --report` prints counts only (no memory text, names or paths), safe to paste into an issue.

## Uninstall

```bash
dawnmere uninstall
```

It stops and removes the background service, takes memory out of Claude Code, Codex and Cursor (putting each file back
as it was before setup, or removing only our entries if you changed the file since), removes the API key from your
Keychain, and removes the `dawnmere` and engine programs. It always asks before deleting your memory, which cannot be
brought back; say no, or use `--keep-data`, to keep it. The backups setup made stay next to each file, and uninstall
lists them.

## Where things live

| what | where |
| --- | --- |
| your memory, settings and models | `~/Library/Application Support/LF Labs/Memory/` (only you can read it) |
| the service's log | `~/Library/Logs/LF Labs/memory.log` |
| the background service | `~/Library/LaunchAgents/com.lflabs.memory.plist` |
| the programs | `~/.local/share/uv/tools/lflabs-memory-cli/`, linked as `~/.local/bin/dawnmere` and `lflabs-memory` |
| an Anthropic API key, if you gave one | your login Keychain, as "LF Labs Memory" |

## Privacy

Your memory stays on your Mac. It is never uploaded, and nothing is sent to LF Labs. There is no usage data.

What does go over the network:

- **Background reading**, if you chose a model: after a Claude Code session goes quiet, that conversation goes to your
  own model provider (your Claude plan through Claude Code, or the Anthropic API with your key) to pick out what is
  worth remembering. At most 200 calls a day.
- **Downloads**: the installer, uv, Python and the engine's Python packages (from GitHub and PyPI); the search models
  and the Claude Code plugin (from this repo on GitHub); the connector (from npm, when an app starts it). `dawnmere
  update` asks GitHub for the newest release.
- **Setup's check of your model**: one short test call to Claude Code or the Anthropic API.

Each app decides for itself what it sends to its own model, including what it recalls from memory.

## License

The installer, the `dawnmere` command, the plugin and the connector: MIT ([LICENSE](LICENSE)). The engine:
[FSL-1.1-MIT](https://github.com/Hadeva-Dev/lflabs-memory-engine/blob/main/LICENSE). The models keep their own
licenses (`dawnmere doctor --licenses`), and the setup screen's wordmark is drawn from the Jost font
([THIRD_PARTY.md](THIRD_PARTY.md)).
