# Directory listings, ready to paste

When the product name changes, change it here, in the README and in `src/brand.ts`
(docs/GO-PUBLIC.md, "Renaming").

Shared by every listing:

- **Name:** Dawnmere
- **One line:** One memory shared across your AI apps: Claude, Cursor, Codex and more, kept on your Mac.
- **Short (100 characters max, the registry's limit):** One memory shared across your AI apps. Connects to Dawnmere on your Mac.
- **Tags:** memory, knowledge-management, cross-app, claude, cursor, codex, local-first, macos
- **Repo:** https://github.com/LF-Labs-Inc/dawnmere
- **Install:** `npx -y dawnmere-connector`
- **Honest status line:** Early beta, macOS only; needs Dawnmere running on the same Mac.

## Official MCP Registry

Nothing to paste: `connector/server.json` is the listing. After the npm package is published, from `connector/`:

```bash
mcp-publisher login github     # as a member of LF-Labs-Inc
mcp-publisher publish
```

PulseMCP picks listings up from the registry.

## awesome-mcp-servers (pull request)

Section: **Knowledge & Memory**, alphabetical. Legend: 📇 TypeScript, 🏠 local, 🍎 macOS.

```markdown
- [LF-Labs-Inc/dawnmere](https://github.com/LF-Labs-Inc/dawnmere) 📇 🏠 🍎 - One memory shared across your AI apps (Claude, Cursor, Codex and more), kept on your Mac by Dawnmere. Recall, remember and forget, with per-app permissions.
```

Most entries now also carry a Glama score badge after the link; add it once Glama has indexed the repo. Check the
list's current legend and section names before opening the PR; they change.

## Smithery

Local server, published as the `.mcpb` from the GitHub release.

- **Display name:** Dawnmere
- **Description:** One memory shared across your AI apps. Claude, Cursor, Codex and the rest read and write the same memory, kept on your Mac by Dawnmere. Early beta, macOS only.
- **Tags:** memory, cross-app, local-first, macos

## Claude plugin directory (claude.ai/directory/manage)

- **Plugin name:** dawnmere
- **Source:** https://github.com/LF-Labs-Inc/dawnmere (`plugin/.claude-plugin/plugin.json`, listed by the root `.claude-plugin/marketplace.json`)
- **Short description:** One memory shared across your AI apps, kept on your Mac.
- **Long description:** Dawnmere gives Claude Code the same memory as your other AI apps. It adds four tools (recall, remember, forget, access_status) that talk to Dawnmere on your Mac. The plugin stores nothing and sends nothing over the network. Early beta: it needs Dawnmere running on the same Mac.
- **Category:** Productivity
- **Install snippet:** `/plugin marketplace add LF-Labs-Inc/dawnmere` then `/plugin install dawnmere@dawnmere`, then `/dawnmere:setup`

## mcp.so (mcp.so/submit)

- **Name:** Dawnmere
- **URL:** https://github.com/LF-Labs-Inc/dawnmere
- **Description:** One memory shared across your AI apps (Claude, Cursor, Codex and more), kept on your Mac. Recall, remember and forget through Dawnmere, with per-app permissions. Early beta, macOS only.
- **Tags:** memory, cross-app, local-first, macos

## MCP Market (mcpmarket.com/submit)

- **GitHub URL:** https://github.com/LF-Labs-Inc/dawnmere
- **Description:** same as mcp.so.

## Glama

Indexes public repos by itself. Once the repo is public, find the listing and claim it with the GitHub account;
the description comes from the README's first paragraph.

## Config snippet for any listing that asks

```json
{
  "mcpServers": {
    "dawnmere": {
      "command": "npx",
      "args": ["-y", "dawnmere-connector"]
    }
  }
}
```
