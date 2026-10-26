# What this repo is, and what it is not

## Decision

This repo is the **connector**: a small, installable MCP server that AI apps launch (Claude Desktop, Claude Code,
Cursor, Codex, Windsurf, VS Code, Gemini CLI). It defines four tools and forwards each call, unchanged, to the
Wayfern app already running on the same Mac, over a local Unix socket. It holds no memory, makes no decisions about
what an app may see, and never touches the network.

Everything that makes Wayfern Wayfern stays in the private engine: storage, search and ranking, claims, saving from
sessions, the safety rules (origins, the trick screen, redaction), per-app permissions, and the remote service. The
public repo can be read in ten minutes and audited by a directory reviewer, and nothing in it is worth copying.

## Why this shape

| choice | why |
|---|---|
| The connector declares its own tools (not a byte pipe to the engine) | Directories (Smithery, Glama, the Claude plugin review) start the server to list its tools. That has to work on a machine without Wayfern. A reviewer can also see exactly what crosses the socket. |
| Four tools: `recall`, `remember`, `forget`, `access_status` | The same surface as Wayfern's remote phase 1, so local and cloud apps see one product. No list-all, no chat-history search: directory rules forbid servers that read an assistant's own chat history, and they are the riskiest tools. |
| A Unix socket, one JSON line each way (`PROTOCOL.md`) | Local only, no port to scan, no auth server. Permissions come from file ownership; the connector refuses a socket some other user owns. |
| TypeScript on npm | `npx -y wayfern-connector` is the install line every MCP directory expects; `.mcpb` bundles run on the Node that ships inside Claude Desktop, so users need nothing installed. The engine's language does not matter here. |
| The app identifies itself; the engine decides | The connector passes along the name it was configured with (`WAYFERN_CLIENT`), an optional key, and the name the app reported. Who sees what is the engine's job, with the same rules as today. |
| The brand lives in `src/brand.ts` and the packaging files | A rename (if the trademark screen asks for one) is one constants file plus the manifests, checked by a test that every version and name agrees. |
| No remote proxy | Cloud apps connect to the Wayfern URL directly with OAuth; a local connector adds nothing there. |

## What the engine needs before this works end to end

The engine's daemon must answer `wayfern-connector/1` requests on the connector socket (`PROTOCOL.md`). Today its
socket answers only `recall` for its own MCP server; `remember`, `forget` and `access_status` run inside that server.
That handler is a small change in the private repo and is not part of this one.

## Out of scope for 0.1

Windows and Linux (the socket path and the Wayfern app are Mac only), any UI, imports, the per-app instruction text.
