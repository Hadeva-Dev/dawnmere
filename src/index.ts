#!/usr/bin/env node
// wayfern-connector            run as an MCP server over stdio (what AI apps launch)
// wayfern-connector --check    say whether the Wayfern app answers on this machine
// wayfern-connector --version
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { PRODUCT, VERSION } from "./brand.js";
import { ask, socketPath } from "./daemon.js";
import { createServer } from "./server.js";

const arg = process.argv[2];

if (arg === "--version" || arg === "-v") {
  console.log(VERSION);
} else if (arg === "--check") {
  const r = await ask("ping", {}, { name: null, key: null, hint: "wayfern-connector --check" });
  console.log(r.ok ? `Connected to ${r.text} at ${socketPath()}` : r.error);
  process.exitCode = r.ok ? 0 : 1;
} else if (arg === undefined) {
  await createServer().connect(new StdioServerTransport());
} else {
  console.error(`usage: wayfern-connector [--check | --version]\nConnects AI apps to ${PRODUCT} on this computer.`);
  process.exitCode = 2;
}
