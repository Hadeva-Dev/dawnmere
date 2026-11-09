#!/usr/bin/env node
// dawnmere-connector            run as an MCP server over stdio (what AI apps launch)
// dawnmere-connector --check    say whether the memory app answers on this machine
// dawnmere-connector --version
// dawnmere-connector --help
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { PACKAGE, PRODUCT, VERSION } from "./brand.js";
import { ask, socketPath } from "./daemon.js";
import { createServer } from "./server.js";

const arg = process.argv[2];
const USAGE = `usage: ${PACKAGE} [--check | --version | --help]\nConnects AI apps to ${PRODUCT} on this computer.`;

if (arg === "--help" || arg === "-h") {
  console.log(USAGE);
} else if (arg === "--version" || arg === "-v") {
  console.log(VERSION);
} else if (arg === "--check") {
  const r = await ask("ping", {}, { name: null, key: null, hint: `${PACKAGE} --check` });
  console.log(r.ok ? `Connected to ${r.text} at ${socketPath()}` : r.error);
  process.exitCode = r.ok ? 0 : 1;
} else if (arg === undefined) {
  await createServer().connect(new StdioServerTransport());
} else {
  console.error(USAGE);
  process.exitCode = 2;
}
