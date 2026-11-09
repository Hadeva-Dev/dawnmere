# Releasing

This repo has no CI: releases are cut by hand on a Mac with Apple silicon, from a clean `main`.
The engine checkout sits next to this repo as `../lflabs-memory-engine`.

1. **Versions.** Set `version` in `cli/pyproject.toml` to the new `X.Y.Z`, the same `X.Y.Z` as `version` in
   `plugin/.claude-plugin/plugin.json` and in the plugin's entry in `.claude-plugin/marketplace.json` (a test checks
   they agree), and put the engine tag to ship in `ENGINE_TAG`. Merge that to `main`, then tag it `vX.Y.Z` and push
   the tag (`git push origin vX.Y.Z`) before anything is published: setup adds the Claude Code marketplace at
   `Hadeva-Dev/dawnmere#vX.Y.Z`, the tag of the CLI it runs from, so the plugin and its hooks change only with a
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
3. **Tests before publishing.**
   ```bash
   (cd cli && uv run pytest -q)
   (cd connector && npm ci && npm test && npm run test:bundle)
   ```
4. **Claude Desktop extension.**
   ```bash
   (cd connector && npm run pack:mcpb) && cp connector/dawnmere-connector.mcpb dist/
   (cd dist && shasum -a 256 dawnmere-connector.mcpb >> SHA256SUMS)
   ```
5. **Publish.** `gh release create "v$VERSION" dist/* --title "v$VERSION" --generate-notes`
6. **Check the install line** in a throwaway home, with a UTF-8 locale like a real Terminal:
   ```bash
   H=$(mktemp -d)
   env -i HOME="$H" PATH=/usr/bin:/bin:/usr/sbin LC_ALL=en_US.UTF-8 LFLABS_MEMORY_NO_SETUP=1 \
     sh -c 'curl -fsSL https://github.com/Hadeva-Dev/dawnmere/releases/latest/download/install.sh | sh'
   PATH="$H/.local/bin:$PATH" HOME="$H" dawnmere setup --yes --plain --backend none && PATH="$H/.local/bin:$PATH" HOME="$H" dawnmere doctor
   ```
