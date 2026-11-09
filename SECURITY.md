# Security

Dawnmere edits your AI apps' settings and keeps your memory on your Mac, so security reports come first.

## Reporting a problem

Please do not open a public issue. Report it privately, either way:

- through GitHub: [report a vulnerability](https://github.com/Hadeva-Dev/dawnmere/security/advisories/new)
  (the Security tab of this repo, then "Report a vulnerability");
- by email: [hello@dawnmere.app](mailto:hello@dawnmere.app).

Say what you found, how to reproduce it, and which version you ran (`dawnmere doctor --report` prints it). We will
reply to say we have it, and tell you when the fix ships.

## What is covered

Everything the install line puts on your Mac: the installer, the `dawnmere` command, the Claude Code plugin, the
connector (`dawnmere-connector` on npm) and the memory engine. Problems such as a way for another app to read memory it
was not given, saved text that turns into instructions for an app, a secret that gets saved, or a download that skips its
checksum are all in scope.

## Supported versions

The latest release only. Fixes ship as a new release; run `dawnmere update` or the install line again to get it.
