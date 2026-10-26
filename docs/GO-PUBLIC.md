# Going public: what only the owner can do

In order. Nothing here is done yet; the repo is private.

## Before anything is public

1. **The trademark screen comes back clear enough for "Wayfern".** If it does not, rename first: `src/brand.ts`,
   the four packaging files (`package.json`, `server.json`, `mcpb/manifest.json`, `.claude-plugin/*.json`), the docs,
   and the repo name. `npm test` fails until every version and name agrees.
2. **The Wayfern app answers the connector protocol.** The engine needs a handler for `docs/PROTOCOL.md` on the
   connector socket. Until then the listing would install something that only says "Wayfern isn't running".
3. **Review the repo once:** README, `docs/`, `src/` (about 200 lines). Commits carry your git name and email,
   as in your other public repos.
4. **Confirm the copyright holder.** `LICENSE` says "LF Labs"; change it if the company's legal name differs.

## Publish

5. **Flip the repo to public:** `gh repo edit Hadeva-Dev/wayfern-connector --visibility public --accept-visibility-change-consequences`.
6. **Publish to npm** (needs an npm account; `wayfern-connector` is free as of 2026-10-25, `wayfern` is taken by another
   company's browser-automation tool that uses the Wayfern name):
   ```bash
   npm login
   npm publish --access public
   ```
7. **Make a GitHub release** with the bundle, so Claude Desktop users can download it:
   ```bash
   npm run pack:mcpb
   gh release create v0.1.0 wayfern-connector.mcpb --title "0.1.0" --notes "Early beta, macOS only."
   ```
8. **Official MCP Registry:** install `mcp-publisher` (`brew install mcp-publisher`), `mcp-publisher login github`
   (a browser sign-in as a member of Hadeva-Dev, which proves the `io.github.Hadeva-Dev/` namespace), then
   `mcp-publisher publish` from the repo root.

## Directories (text in `docs/LISTING.md`)

9. **awesome-mcp-servers:** a pull request adding one line. Claude can open it once you say so.
10. **Smithery:** sign in with GitHub and publish the release's `.mcpb`.
11. **Claude plugin directory:** needs a paid Claude plan; submit the repo at claude.ai/directory/manage. It is
    scanned, then reviewed.
12. **mcp.so, MCP Market:** paste the repo URL (paid fast lanes: $39 and $29, both optional).
13. **Glama:** claim the listing it creates from the public repo.

## After each release

Bump the version in `src/brand.ts` and the packaging files together (the tests check), then repeat 6 to 8.
