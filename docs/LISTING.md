# Directory listings, ready to paste

Shared by every listing:

- **Name:** Wayfern
- **One line:** One memory shared across your AI apps: Claude, Cursor, Codex and more, kept on your Mac.
- **Short (100 characters max, the registry's limit):** One memory shared across your AI apps. Connects to the Wayfern app on your Mac.
- **Tags:** memory, knowledge-management, cross-app, claude, cursor, codex, local-first, macos
- **Repo:** https://github.com/Hadeva-Dev/wayfern-connector
- **Install:** `npx -y wayfern-connector`
- **Honest status line:** Early beta, macOS only; needs the Wayfern app running on the same Mac.

## Official MCP Registry

Nothing to paste: `server.json` in the repo root is the listing. After the npm package is published:

```bash
mcp-publisher login github     # as a member of Hadeva-Dev
mcp-publisher publish
```

PulseMCP picks listings up from the registry.

## awesome-mcp-servers (pull request)

Section: **Knowledge & Memory**, alphabetical. Legend: 📇 TypeScript, 🏠 local, 🍎 macOS.

```markdown
- [Hadeva-Dev/wayfern-connector](https://github.com/Hadeva-Dev/wayfern-connector) 📇 🏠 🍎 - One memory shared across your AI apps (Claude, Cursor, Codex and more), kept on your Mac by the Wayfern app. Recall, remember and forget, with per-app permissions.
```

Most entries now also carry a Glama score badge after the link; add it once Glama has indexed the repo. Check the
list's current legend and section names before opening the PR; they change.

## Smithery

Local server, published as the `.mcpb` from the GitHub release.

- **Display name:** Wayfern
- **Description:** One memory shared across your AI apps. Claude, Cursor, Codex and the rest read and write the same memory, kept on your Mac by the Wayfern app. Early beta, macOS only.
- **Tags:** memory, cross-app, local-first, macos

## Claude plugin directory (claude.ai/directory/manage)

- **Plugin name:** wayfern
- **Source:** https://github.com/Hadeva-Dev/wayfern-connector (`.claude-plugin/plugin.json`)
- **Short description:** One memory shared across your AI apps, kept on your Mac.
- **Long description:** Wayfern gives Claude Code the same memory as your other AI apps. It adds four tools (recall, remember, forget, access_status) that talk to the Wayfern app on your Mac. The plugin stores nothing and sends nothing over the network. Early beta: it needs the Wayfern app running on the same Mac.
- **Category:** Productivity
- **Install snippet:** `/plugin marketplace add Hadeva-Dev/wayfern-connector` then `/plugin install wayfern@wayfern`

## mcp.so (mcp.so/submit)

- **Name:** Wayfern
- **URL:** https://github.com/Hadeva-Dev/wayfern-connector
- **Description:** One memory shared across your AI apps (Claude, Cursor, Codex and more), kept on your Mac. Recall, remember and forget through the Wayfern app, with per-app permissions. Early beta, macOS only.
- **Tags:** memory, cross-app, local-first, macos

## MCP Market (mcpmarket.com/submit)

- **GitHub URL:** https://github.com/Hadeva-Dev/wayfern-connector
- **Description:** same as mcp.so.

## Glama

Indexes public repos by itself. Once the repo is public, find the listing and claim it with the GitHub account;
the description comes from the README's first paragraph.

## Config snippet for any listing that asks

```json
{
  "mcpServers": {
    "wayfern": {
      "command": "npx",
      "args": ["-y", "wayfern-connector"]
    }
  }
}
```
