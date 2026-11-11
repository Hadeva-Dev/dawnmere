# Contributing

Thanks for helping. Dawnmere is early and small, so the most useful things right now are bug reports with
`dawnmere doctor --report` attached, and notes on where setup or the docs confused you.

## Before you start

For anything bigger than a small fix, open an issue or a discussion first, so we can agree on the approach before you
spend time on it. Security problems go through [SECURITY.md](SECURITY.md), never a public issue.

## What lives where

| Path | What it is |
| --- | --- |
| `install.sh` | the installer template; a release fills in the version and checksums |
| `cli/` | the `dawnmere` command (Python): setup, doctor, update, uninstall |
| `connector/` | `dawnmere-connector`, the MCP server each app runs (TypeScript, published to npm) |
| `plugin/` | the Claude Code plugin: its hooks and MCP entry |

The memory engine (storage, search, screening) is a separate repo,
[dawnmere-engine](https://github.com/LF-Labs-Inc/dawnmere-engine). The CLI's tests expect it checked out next
to this repo, in a folder named `lflabs-memory-engine`.

## Running the tests

You need a Mac with Apple silicon, [uv](https://github.com/astral-sh/uv) and Node.js 22 or later (the connector runs on
18; its tests need 22).

```bash
git clone https://github.com/LF-Labs-Inc/dawnmere.git
git clone https://github.com/LF-Labs-Inc/dawnmere-engine.git lflabs-memory-engine
(cd dawnmere/cli && uv run pytest -q)
(cd dawnmere/connector && npm ci && npm test)
```

There is no CI; please run both before you open a pull request, and say in it that they pass.

## Pull requests

- One change per pull request, with a description of what a user would notice.
- Keep the voice of the existing text: short, plain sentences that say exactly what happens.
- By contributing you agree that your change is licensed under the license of the part you changed: MIT for this repo
  ([LICENSE](LICENSE)), FSL-1.1-MIT for the engine.
