// The packaging files must agree with the code: one version, one name, the same tools. A rename or a release that
// forgets one of them fails here.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { VERSION } from "../dist/brand.js";

const json = (p) => JSON.parse(readFileSync(new URL(`../${p}`, import.meta.url), "utf8"));
const pkg = json("package.json");
const server = json("server.json");
const manifest = json("mcpb/manifest.json");
const plugin = json(".claude-plugin/plugin.json");
const market = json(".claude-plugin/marketplace.json");

test("one version everywhere", () => {
  for (const v of [pkg.version, server.version, server.packages[0].version, manifest.version, plugin.version,
    market.plugins[0].version]) assert.equal(v, VERSION);
  assert.deepEqual(plugin.mcpServers.wayfern.args, ["-y", `${pkg.name}@${VERSION}`]);
});

test("the registry name and the npm package point at each other", () => {
  assert.equal(pkg.mcpName, server.name);
  assert.equal(server.packages[0].identifier, pkg.name);
  assert.equal(server.packages[0].registryType, "npm");
  assert.equal(manifest.name, pkg.name);
  assert.ok(server.description.length <= 100, "the registry caps descriptions at 100 characters");
});

test("the bundle lists the tools the server registers", () => {
  assert.deepEqual(manifest.tools.map((t) => t.name).sort(), ["access_status", "forget", "recall", "remember"]);
});

test("MIT everywhere", () => {
  for (const l of [pkg.license, manifest.license, plugin.license]) assert.equal(l, "MIT");
  assert.match(readFileSync(new URL("../LICENSE", import.meta.url), "utf8"), /^MIT License/);
});
