# Connector protocol, version 1

How the connector talks to the Wayfern app on the same machine. Any program that answers this protocol on the socket
can stand in for Wayfern (the tests do exactly that).

## The socket

- `WAYFERN_SOCKET` if set, else `~/Library/Application Support/Wayfern/connector.sock`.
- The connector connects only if the path is a socket owned by the user running the connector. Anything else (a
  missing file, a regular file, another user's socket) is reported as "Wayfern isn't running".

## One request, one reply

The connector opens a connection, writes one JSON object followed by `\n`, reads one JSON line back, and closes.

```json
{"protocol": "wayfern-connector/1",
 "tool": "recall",
 "args": {"query": "what editor does the user prefer", "k": 8},
 "client": {"name": "cursor", "key": null, "hint": "cursor-vscode", "connector": "0.1.0"}}
```

| field | meaning |
|---|---|
| `protocol` | always `wayfern-connector/1`. A daemon that does not speak it should answer `{"ok": false, "error": "..."}`. |
| `tool` | `recall`, `remember`, `forget`, `access_status`, or `ping` (the connector's `--check`). |
| `args` | the tool's arguments, already checked against the schemas below. |
| `client.name` | `WAYFERN_CLIENT`, the name the app's config gives, or `null`. A label the engine may hold to its narrowest default. |
| `client.key` | `WAYFERN_CLIENT_KEY` or `null`. The connector never logs it. |
| `client.hint` | the name the app reported when it connected (MCP `clientInfo.name`), or `null`. Never trusted on its own. |
| `client.connector` | the connector's version. |

Reply:

```json
{"ok": true, "text": "..."}
{"ok": false, "error": "a sentence the AI can show the user"}
```

`text` is shown to the AI as the tool's result; an `error` comes back as a tool error. A reply larger than 1 MiB, a
reply that is not one JSON object, or no reply within `WAYFERN_TIMEOUT_MS` (default 15000) is an error.

## Tool arguments

| tool | args |
|---|---|
| `recall` | `query` (string, 1 to 2000 characters), `k` (integer 1 to 20, optional), `section` (string up to 64, optional) |
| `remember` | `content` (string, 1 to 4000), `kind` (`user`, `feedback`, `project`, `reference` or `note`, optional), `project` (string up to 100, optional) |
| `forget` | `id` (a memory id as recall shows it: digits, or `c` and digits) |
| `access_status` | none |
| `ping` | none; answer `{"ok": true, "text": "<app name and version>"}` |

The engine applies its own limits on top (results, characters, rate) and its own permissions. The connector's checks
only keep malformed calls off the socket.
