---
description: Install Dawnmere on this Mac and connect your AI apps to one memory
---

The user wants Dawnmere set up on this Mac: the `dawnmere` command and its memory engine, then `dawnmere setup`,
which connects Claude Code, Codex, Cursor and their other AI apps to one local memory. Walk them through it. Keep
your messages short; this Claude Code session sees the output, so don't paste it back in full.

Ground rules (they keep Dawnmere's safety checks intact):
- Install only with the official install line below, exactly as written. It serves `install.sh` from Dawnmere's
  latest GitHub release, which checks every file against its sha256 before installing anything. Never fetch or run
  another script.
- Run each command in its own Bash call, so the user approves each one.
- Never add `--yes` to `dawnmere setup` unless the user says so after seeing what it will change.
- Never run `dawnmere access`, `dawnmere trust` or `dawnmere setup` to give an app more than work notes, and never
  try to answer a macOS dialog. Dawnmere only allows that from a real Terminal window, by the user.

## 1. Is it already here?

Run `command -v dawnmere || ls ~/.local/bin/dawnmere`. If it's found and
`~/Library/Application Support/LF Labs/Memory/config.toml` exists, Dawnmere is already set up: run `dawnmere doctor`
(or `~/.local/bin/dawnmere doctor`), tell the user what it found in a sentence or two, and stop.

## 2. Install it

Tell the user, in one or two sentences, that this downloads Dawnmere (and uv, if it isn't installed) from GitHub,
checks every file's hash, and installs it in their home folder. It needs macOS 14 or later on Apple silicon. Then run:

```
curl -fsSL https://dawnmere.app/install | LFLABS_MEMORY_NO_SETUP=1 sh
```

`LFLABS_MEMORY_NO_SETUP=1` stops the installer before setup, which asks its questions in a terminal that this
session doesn't have. If the installer fails, show its last lines and stop; it changes nothing when a check fails.

## 3. Set it up

`dawnmere setup` asks a few questions (what your apps should call you, which model reads in the background, whether
to import Claude Code's notes) and can confirm the imported notes in one macOS dialog. Offer two ways, and recommend
the first:

1. **In Terminal (recommended).** Ask the user to open a new Terminal window and run `dawnmere setup`. If the new
   window doesn't find it, `~/.local/bin/dawnmere setup` works. Wait for them to say it's done, then go to step 4.
2. **Here, with the defaults.** First run `~/.local/bin/dawnmere setup --dry-run`, then sum up in a few lines what it
   would change. Only if the user then says yes, run `~/.local/bin/dawnmere setup --yes`. Tell them what the defaults
   mean: Cursor and the apps connected through their MCP file alone (Windsurf, VS Code and the like) see work
   notes only, and notes imported from Claude Code stay held until they run `dawnmere held` and then
   `dawnmere trust` in Terminal.

## 4. Check it

Run `~/.local/bin/dawnmere doctor` and give the user its result in a sentence or two. Setup reinstalls this plugin at
the release it installed, so tell them to restart Claude Code: memory's tools and hooks load in the next session.
