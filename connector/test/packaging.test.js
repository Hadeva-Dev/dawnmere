// The packaging files must agree with the code: one version, one name, the same tools. A rename or a release that
// forgets one of them fails here.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { COMMAND, PACKAGE, PRODUCT, SERVER_NAME, VERSION } from "../dist/brand.js";

const json = (p) => JSON.parse(readFileSync(new URL(`../${p}`, import.meta.url), "utf8"));
const pkg = json("package.json");
const server = json("server.json");
const manifest = json("mcpb/manifest.json");
// The Claude Code plugin lives at the distribution repo's root (plugin/, .claude-plugin/): it carries this connector
// and the engine's hooks.
const plugin = json("../plugin/.claude-plugin/plugin.json");
const pluginMcp = json("../plugin/.mcp.json");
const market = json("../.claude-plugin/marketplace.json");

test("one version everywhere", () => {
  for (const v of [pkg.version, server.version, server.packages[0].version, manifest.version]) assert.equal(v, VERSION);
  // the Claude Code plugin ships with each CLI release (its marketplace is pinned to that tag, cli/tests
  // test_versions_agree): its own version is the CLI's, and it runs this connector's version
  assert.equal(plugin.version, market.plugins[0].version);
  assert.deepEqual(pluginMcp.mcpServers[SERVER_NAME].args, ["-y", `${pkg.name}@${VERSION}`]);
});

test("the registry name and the npm package point at each other", () => {
  assert.equal(pkg.name, PACKAGE);
  assert.ok(pluginMcp.mcpServers[SERVER_NAME]);
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

// The product name may change. It may appear only where a rename has to touch anyway: brand.ts, the usage comment,
// the README, the listing and design text, and the packaging files, whose package, registry and bundle names carry it
// by decision (docs/GO-PUBLIC.md, "Renaming").
const BRANDED = ["src/brand.ts", "src/index.ts", "README.md", "docs/LISTING.md", "docs/DESIGN.md", "docs/GO-PUBLIC.md",
  "package.json", "package-lock.json", "server.json", "mcpb/manifest.json"];

test("the product name lives only in the files a rename touches", () => {
  const tracked = execFileSync("git", ["ls-files", "--cached", "--others", "--exclude-standard"], {
    cwd: new URL("..", import.meta.url),
    encoding: "utf8",
  }).split("\n").filter(Boolean);
  const name = new RegExp(PRODUCT, "i");
  const stray = tracked.filter((f) => !BRANDED.includes(f) && name.test(readFileSync(new URL(`../${f}`, import.meta.url), "utf8")));
  assert.deepEqual(stray, []);
  // The package family is the command's name plus "-connector"; since 0.1.10 the server id, the plugin and the
  // marketplace are the command's name too (the CLI renames an older install's "lflabs-memory" entries).
  assert.equal(PACKAGE, `${COMMAND}-connector`);
  for (const id of [pkg.name, pkg.mcpName, server.name, manifest.name]) assert.match(id, name);
  for (const id of [plugin.name, market.name, market.plugins[0].name, SERVER_NAME]) assert.equal(id, COMMAND);
});
