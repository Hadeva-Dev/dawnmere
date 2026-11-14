# Releasing

This repo has no CI: releases are cut by hand on a Mac with Apple silicon, from a clean `main`.
The engine checkout sits next to this repo as `../lflabs-memory-engine`.

1. **Versions.** Set `version` in `cli/pyproject.toml` to the new `X.Y.Z`, the same `X.Y.Z` as `version` in
   `plugin/.claude-plugin/plugin.json` and in the plugin's entry in `.claude-plugin/marketplace.json` (a test checks
   they agree), and put the engine tag to ship in `ENGINE_TAG`. Merge that to `main`, then tag it `vX.Y.Z` and push
   the tag (`git push origin vX.Y.Z`) before anything is published: setup adds the Claude Code marketplace at
   `LF-Labs-Inc/dawnmere#vX.Y.Z`, the tag of the CLI it runs from, so the plugin and its hooks change only with a
   release, never with a push to `main`, and an install fails over to the settings.json hooks if the tag is missing.
   `dawnmere update` moves the plugin to the new tag (marketplace remove, add at the tag, install).
2. **Wheels and the installer.**
   ```bash
   VERSION=X.Y.Z
   (cd ../lflabs-memory-engine && git checkout "$(cat ../lflabs-memory/ENGINE_TAG)")
   rm -rf dist && uv build --wheel --out-dir dist cli && uv build --wheel --out-dir dist ../lflabs-memory-engine
   CLI=$(ls dist/lflabs_memory_cli-*.whl) ENGINE=$(ls dist/lflabs_memory_engine-*.whl)
   # every dependency of the two wheels, pinned with its hashes, for the Macs install.sh supports (macOS 14+, arm64,
   # Python 3.12); the two wheels are checked by their own sha256 instead
   printf '%s\n' "$CLI" "$ENGINE" | MACOSX_DEPLOYMENT_TARGET=14.0 uv pip compile - --generate-hashes \
     --python-version 3.12 --python-platform aarch64-apple-darwin --no-header --quiet \
     --no-emit-package lflabs-memory-cli --no-emit-package lflabs-memory-engine -o dist/constraints.txt
   uv run --no-project python cli/tools/render_install.py "$VERSION" "$CLI" "$ENGINE" dist/constraints.txt dist/install.sh
   (cd dist && shasum -a 256 *.whl constraints.txt install.sh > SHA256SUMS)
   ```
   install.sh and `dawnmere update` first download every dependency with uv's Python 3.12 and
   `pip download --require-hashes --only-binary :all: --no-deps -r constraints.txt` (uv tool install does not
   check the hashes in a constraints file), then `uv tool install --no-index --find-links` those files only; a
   release without constraints.txt is refused.
3. **The connector on npm, before step 1's merge.** If `connector/package.json`'s version changed:
   ```bash
   (cd connector && npm ci && npm test && npm publish)   # dawnmere-connector X.Y.Z
   npm view "dawnmere-connector@$(node -p "require('./connector/package.json').version")" version   # prints it
   ```
   Do this BEFORE merging the release PR to `main` (step 1): `plugin/.mcp.json` on `main` pins that version, and the
   marketplace of a 0.1.5 install follows `main`, so a merged pin that is not published yet leaves those apps
   unable to start memory's tools (doctor and setup say so).
4. **Tests before publishing.**
   ```bash
   (cd cli && uv run pytest -q)
   (cd connector && npm ci && npm test && npm run test:bundle)
   ```
5. **Claude Desktop extension.**
   ```bash
   (cd connector && npm run pack:mcpb) && cp connector/dawnmere-connector.mcpb dist/
   (cd dist && shasum -a 256 dawnmere-connector.mcpb >> SHA256SUMS)
   ```
6. **Publish.** `gh release create "v$VERSION" dist/* --title "v$VERSION" --generate-notes`
7. **The engine's public snapshot.** After the release is published, publish the engine tag it ships (`ENGINE_TAG`)
   to the public engine repo as one new commit, by `dawnmere-launch/engine-public/publish-steps.md` section 9.
   `export.sh` needs Python 3.11 or later (it reads the version with `tomllib`), so put uv's on PATH first:
   ```bash
   PATH="$(dirname "$(uv python find 3.12)"):$PATH" "$LAUNCH/engine-public/export.sh" "$(cat ENGINE_TAG)" /tmp/engine-"$(cat ENGINE_TAG)"
   ```
   The export scans its own tree. A real word the scan flags in one file only (a dictionary word, say) goes in
   `scan.sh`'s per-line allowlist (`ALLOW_LINE`, the file and the line, with why), never in the global one.
   Never push to the public engine repo except by those steps.
8. **Check the install line** on a Mac that is not yours: a VM (`dawnmere-launch/vm/`) or a separate macOS user.
   A throwaway HOME on your own Mac is not separate from launchd: setup's `launchctl bootstrap gui/$UID` replaces
   whatever is registered as `com.lflabs.memory`, so it stops your real memory service, and the service it starts
   then reads your real HOME's `~/.claude` and uses your real connector socket. In the VM, with a UTF-8 locale like a
   real Terminal, signed in as the VM's own user with its real HOME (not a `mktemp -d` HOME there either: under
   `/var/folders` the service's socket path is past macOS's 104-byte limit, so the service does not start, and the
   connector socket follows the login user's HOME whatever HOME setup is given):
   ```bash
   env -i HOME="$HOME" PATH=/usr/bin:/bin:/usr/sbin LC_ALL=en_US.UTF-8 LFLABS_MEMORY_NO_SETUP=1 \
     sh -c 'curl -fsSL https://github.com/LF-Labs-Inc/dawnmere/releases/latest/download/install.sh | sh'
   PATH="$HOME/.local/bin:$PATH" dawnmere setup --yes --plain --backend none && PATH="$HOME/.local/bin:$PATH" dawnmere doctor
   ```
