# Going public: what only the owner can do

In order. Nothing is published yet.

## Before anything is public

1. **Pick the product name.** Done: it is in `src/brand.ts`, and "Renaming" below lists every place it appears.
2. **The memory app answers the connector protocol.** Done: the engine's daemon answers `docs/PROTOCOL.md` on the
   connector socket (checked end to end on 2026-11-07). Users still need the engine installed and running.
3. **Review the repo once:** README, `docs/`, `src/` (about 230 lines). Commits carry your git name and email, as in
   your other public repos. Early commit messages mention the old working name; squash them before the flip if that
   matters.
4. **Confirm the copyright holder.** `LICENSE` says "LF Labs"; change it if the company's legal name differs.

## Renaming

The npm package carries the product name (`dawnmere-connector`, with the registry name, the bundle name and the
`bin` to match; decided 2026-11-07, before the first publish, because the `npx` line in every app's config is the
most visible identifier after the install line). Since 0.1.10 the server id, the plugin and its marketplace are
`dawnmere` too (the CLI renames an older install's `lflabs-memory` entries); settings, socket and protocol names stay
neutral (`lflabs-memory-*`). The repo is named after the product. The product name appears only in:

- `src/brand.ts` (`PRODUCT`, `COMMAND`, `PACKAGE`) and the usage comment in `src/index.ts`
- `README.md`, `docs/LISTING.md`, `docs/DESIGN.md` and this file (the repo's URL and the package name)
- `package.json` and `package-lock.json` (the package name), `server.json` (the registry name), `mcpb/manifest.json`
  (the bundle name), `../plugin/.mcp.json`, the CLI's `layout.py` and tests, and the release workflow (the bundle file)
- the display text in `package.json`, `server.json`, `mcpb/manifest.json`, `../plugin/.claude-plugin/plugin.json` and
  `../.claude-plugin/marketplace.json`

`npm test` fails if the name turns up anywhere else, so a rename is a search and replace over those files plus a test
run. A product rename after the first npm publish also means a new package name, with the old one deprecated and
pointing at the new one, so pick the name before publishing.

## Publish

5. **Flip the repo to public:** `gh repo edit LF-Labs-Inc/dawnmere --visibility public --accept-visibility-change-consequences`.
6. **Publish to npm** (needs an npm account with two-factor auth; `dawnmere-connector` was free on 2026-11-07):
   ```bash
   cd connector   npm login
   npm publish --access public --otp=<the code from your authenticator>
   ```
7. **Make a GitHub release** with the bundle, so Claude Desktop users can download it: push the tag `v0.1.0`, and
   the repo's release workflow builds `dawnmere-connector.mcpb` and attaches it with the installer.
8. **Official MCP Registry:** `brew install mcp-publisher`, `mcp-publisher login github` (a browser sign-in as a
   member of LF-Labs-Inc, which proves the `io.github.Hadeva-Dev/` namespace), then `mcp-publisher publish` from
   `connector/`.

## Directories (text in `docs/LISTING.md`)

9. **awesome-mcp-servers:** a pull request adding one line. Claude can open it once you say so.
10. **Smithery:** sign in with GitHub and publish the release's `.mcpb`.
11. **Claude plugin directory:** needs a paid Claude plan; submit the repo at claude.ai/directory/manage. It is
    scanned, then reviewed.
12. **mcp.so, MCP Market:** paste the repo URL (paid fast lanes: $39 and $29, both optional).
13. **Glama:** claim the listing it creates from the public repo.

## After each release

Bump the version in `src/brand.ts` and the packaging files together (the tests check), then repeat 6 to 8.
