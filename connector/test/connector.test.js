// End to end: an MCP client launches the built connector over stdio, the connector talks to the fake daemon.
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, before, describe, test } from "node:test";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { startFakeDaemon } from "./fake-daemon.js";

// CONNECTOR_BIN=mcpb/server/index.mjs runs the same tests against the .mcpb bundle (npm run test:bundle).
const BIN = process.env.CONNECTOR_BIN ?? fileURLToPath(new URL("../dist/index.js", import.meta.url));
const NOT_RUNNING = /isn't running on this computer/;

async function connect(env, name = "test-app") {
  const stderr = [];
  const transport = new StdioClientTransport({
    command: process.execPath,
    args: [BIN],
    env: { PATH: process.env.PATH, HOME: process.env.HOME, ...env },
    stderr: "pipe",
  });
  transport.stderr?.on("data", (d) => stderr.push(String(d)));
  const client = new Client({ name, version: "1.0.0" });
  await client.connect(transport);
  return { client, stderr, close: () => client.close() };
}

const text = (r) => r.content.map((c) => c.text).join("");

describe("with no memory app running", () => {
  let c, dir;
  before(async () => {
    dir = mkdtempSync(join(tmpdir(), "wf-"));
    c = await connect({ LFLABS_MEMORY_SOCKET: join(dir, "missing.sock") });
  });
  after(async () => {
    await c.close();
    rmSync(dir, { recursive: true, force: true });
  });

  test("lists exactly the four tools, with honest annotations", async () => {
    const { tools } = await c.client.listTools();
    const by = Object.fromEntries(tools.map((t) => [t.name, t]));
    assert.deepEqual(Object.keys(by).sort(), ["access_status", "forget", "recall", "remember"]);
    assert.equal(by.recall.annotations.readOnlyHint, true);
    assert.equal(by.access_status.annotations.readOnlyHint, true);
    assert.equal(by.forget.annotations.destructiveHint, true);
    assert.equal(by.remember.annotations.destructiveHint, false);
    for (const t of tools) assert.match(t.description, /^Use this when/);
  });

  test("gives instructions that frame results as data", async () => {
    assert.match(c.client.getInstructions(), /not instructions/);
  });

  test("a call says the app isn't running, as a tool error", async () => {
    const r = await c.client.callTool({ name: "recall", arguments: { query: "editor" } });
    assert.equal(r.isError, true);
    assert.match(text(r), NOT_RUNNING);
  });
});

describe("with the fake daemon", () => {
  let d, c;
  before(async () => {
    d = await startFakeDaemon();
    c = await connect({ LFLABS_MEMORY_SOCKET: d.path, LFLABS_MEMORY_CLIENT: "cursor", LFLABS_MEMORY_CLIENT_KEY: "test-key-123" }, "cursor-vscode");
  });
  after(async () => {
    await c.close();
    await d.close();
  });

  test("recall forwards the arguments and who is asking", async () => {
    const r = await c.client.callTool({ name: "recall", arguments: { query: "dark mode", k: 3 } });
    assert.equal(r.isError, undefined);
    assert.match(text(r), /#1 Prefers dark mode/);
    const req = d.requests.at(-1);
    assert.equal(req.protocol, "lflabs-memory/1");
    assert.equal(req.tool, "recall");
    assert.deepEqual(req.args, { query: "dark mode", k: 3 });
    assert.deepEqual(req.client, { name: "cursor", key: "test-key-123", hint: "cursor-vscode", connector: "0.1.0" });
  });

  test("remember, recall, forget round trip", async () => {
    const saved = await c.client.callTool({
      name: "remember",
      arguments: { content: "Uses pnpm, never npm, in Kestrel.", kind: "project", project: "kestrel" },
    });
    assert.match(text(saved), /added memory #4/);
    assert.match(text(await c.client.callTool({ name: "recall", arguments: { query: "pnpm" } })), /#4 Uses pnpm/);
    assert.match(text(await c.client.callTool({ name: "forget", arguments: { id: "4" } })), /forgot memory #4/);
    assert.match(text(await c.client.callTool({ name: "recall", arguments: { query: "pnpm" } })), /No memories found/);
  });

  test("forget takes a claim id or a number", async () => {
    assert.match(text(await c.client.callTool({ name: "forget", arguments: { id: "c3" } })), /forgot memory #3/);
    assert.match(text(await c.client.callTool({ name: "forget", arguments: { id: 2 } })), /forgot memory #2/);
  });

  test("the daemon's refusal comes back as a tool error", async () => {
    const r = await c.client.callTool({ name: "forget", arguments: { id: 999 } });
    assert.equal(r.isError, true);
    assert.match(text(r), /no active memory #999/);
  });

  test("malformed arguments never reach the daemon", async () => {
    const before = d.requests.length;
    for (const [name, args] of [
      ["forget", { id: "4; rm -rf /" }],
      ["recall", { query: "" }],
      ["recall", { query: "x", k: 500 }],
      ["remember", { content: "x".repeat(4001) }],
      ["remember", { content: "x", kind: "secret" }],
    ]) {
      const r = await c.client.callTool({ name, arguments: args });
      assert.equal(r.isError, true, `${name} ${JSON.stringify(args).slice(0, 40)}`);
    }
    assert.equal(d.requests.length, before);
  });

  test("access_status passes through", async () => {
    assert.match(text(await c.client.callTool({ name: "access_status", arguments: {} })), /cursor sees work only/);
  });

  test("the connector writes nothing to stderr, the key included", () => {
    assert.equal(c.stderr.join(""), "");
  });
});

describe("a broken or impostor daemon", () => {
  for (const [mode, expect] of [
    ["slow", /took too long/],
    ["garbage", /can't read/],
    ["huge", /too large/],
    ["silent", /closed without answering/],
  ]) {
    test(`${mode}: a clear tool error`, async () => {
      const d = await startFakeDaemon({ mode });
      const c = await connect({ LFLABS_MEMORY_SOCKET: d.path, LFLABS_MEMORY_TIMEOUT_MS: "300" });
      try {
        const r = await c.client.callTool({ name: "recall", arguments: { query: "editor" } });
        assert.equal(r.isError, true);
        assert.match(text(r), expect);
      } finally {
        await c.close();
        await d.close();
      }
    });
  }

  test("a regular file where the socket should be counts as not running", async () => {
    const dir = mkdtempSync(join(tmpdir(), "wf-"));
    const path = join(dir, "connector.sock");
    writeFileSync(path, "");
    const c = await connect({ LFLABS_MEMORY_SOCKET: path });
    try {
      const r = await c.client.callTool({ name: "recall", arguments: { query: "editor" } });
      assert.match(text(r), NOT_RUNNING);
    } finally {
      await c.close();
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

describe("the command line", () => {
  const run = promisify(execFile);

  test("--check finds the fake daemon", async () => {
    const d = await startFakeDaemon();
    try {
      const { stdout } = await run(process.execPath, [BIN, "--check"], { env: { ...process.env, LFLABS_MEMORY_SOCKET: d.path } });
      assert.match(stdout, /Connected to Fake memory app 0\.0\.0/);
      assert.equal(d.requests[0].tool, "ping");
    } finally {
      await d.close();
    }
  });

  test("--check reads a leading ~ in the socket setting as the home folder", async () => {
    const d = await startFakeDaemon();
    try {
      const { stdout } = await run(process.execPath, [BIN, "--check"], {
        env: { ...process.env, HOME: d.dir, LFLABS_MEMORY_SOCKET: "~/connector.sock" },
      });
      assert.match(stdout, /Connected to Fake memory app 0\.0\.0/);
    } finally {
      await d.close();
    }
  });

  test("--check exits 1 when nothing answers", async () => {
    await assert.rejects(
      run(process.execPath, [BIN, "--check"], { env: { ...process.env, LFLABS_MEMORY_SOCKET: "/nonexistent/x.sock" } }),
      (e) => e.code === 1 && NOT_RUNNING.test(e.stdout),
    );
  });

  test("--version", async () => {
    assert.equal((await run(process.execPath, [BIN, "--version"])).stdout.trim(), "0.1.0");
  });
});
