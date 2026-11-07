# Going public: what only the owner can do

In order. Nothing here is done yet; the repo is private and nothing is published.

## Before anything is public

1. **Pick the product name.** The first trademark pass knocked out the working name, so the listings wait for a new
   one. Then follow "Renaming" below.
2. **The memory app answers the connector protocol.** Done: the engine's daemon answers `docs/PROTOCOL.md` on the
   connector socket (checked end to end on 2026-11-07). Users still need the engine installed and running.
3. **Review the repo once:** README, `docs/`, `src/` (about 230 lines). Commits carry your git name and email, as in
   your other public repos. Early commit messages mention the old working name; squash them before the flip if that
   matters.
4. **Confirm the copyright holder.** `LICENSE` says "LF Labs"; change it if the company's legal name differs.

## Renaming

The package, server id, settings, socket, protocol and repo names are neutral (`lflabs-memory-*`) and do not change.
The product name appears only in:

- `src/brand.ts` (`PRODUCT`)
- `README.md` and `docs/LISTING.md`
- the display text in `package.json`, `server.json`, `mcpb/manifest.json` and `.claude-plugin/*.json`

`npm test` fails if the name turns up anywhere else, so a rename is a search and replace over those files plus a test
run. If the new name should also be the package name, that is a bigger change: package, `mcpName`, registry name and
plugin name together (the tests check they agree), done before the first npm publish, never after.

## Publish

5. **Flip the repo to public:** `gh repo edit Hadeva-Dev/lflabs-memory-connector --visibility public --accept-visibility-change-consequences`.
6. **Publish to npm** (needs an npm account; `lflabs-memory-connector` was free on 2026-10-25):
   ```bash
   npm login
   npm publish --access public
   ```
7. **Make a GitHub release** with the bundle, so Claude Desktop users can download it:
   ```bash
   npm run pack:mcpb
   gh release create v0.1.0 lflabs-memory-connector.mcpb --title "0.1.0" --notes "Early beta, macOS only."
   ```
8. **Official MCP Registry:** `brew install mcp-publisher`, `mcp-publisher login github` (a browser sign-in as a
   member of Hadeva-Dev, which proves the `io.github.Hadeva-Dev/` namespace), then `mcp-publisher publish` from the
   repo root.

## Directories (text in `docs/LISTING.md`)

9. **awesome-mcp-servers:** a pull request adding one line. Claude can open it once you say so.
10. **Smithery:** sign in with GitHub and publish the release's `.mcpb`.
11. **Claude plugin directory:** needs a paid Claude plan; submit the repo at claude.ai/directory/manage. It is
    scanned, then reviewed.
12. **mcp.so, MCP Market:** paste the repo URL (paid fast lanes: $39 and $29, both optional).
13. **Glama:** claim the listing it creates from the public repo.

## After each release

Bump the version in `src/brand.ts` and the packaging files together (the tests check), then repeat 6 to 8.
