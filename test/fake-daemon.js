// A stand-in for the Wayfern app: answers docs/PROTOCOL.md on a socket in a temp folder, from a made-up memory.
// No real memory is ever read by the tests.
import { mkdtempSync, rmSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";

const SEED = [
  { id: 1, text: "Prefers dark mode in every editor." },
  { id: 2, text: "Project Kestrel ships on Fridays; release notes go in CHANGES.md." },
  { id: 3, text: "Dana Ortiz is the design lead on Kestrel." },
];

export async function startFakeDaemon({ mode = "normal" } = {}) {
  const dir = mkdtempSync(join(tmpdir(), "wf-"));
  const path = join(dir, "connector.sock");
  const memories = SEED.map((m) => ({ ...m }));
  const requests = [];

  const answer = (req) => {
    if (req.protocol !== "wayfern-connector/1") return { ok: false, error: "unknown protocol" };
    const a = req.args || {};
    switch (req.tool) {
      case "ping":
        return { ok: true, text: "Fake Wayfern 0.0.0" };
      case "recall": {
        const words = String(a.query).toLowerCase().split(/\W+/).filter(Boolean);
        const hits = memories.filter((m) => words.some((w) => m.text.toLowerCase().includes(w))).slice(0, a.k ?? 8);
        return { ok: true, text: hits.length ? hits.map((m) => `#${m.id} ${m.text}`).join("\n") : "No memories found." };
      }
      case "remember": {
        const id = memories.length + 1;
        memories.push({ id, text: a.content });
        return { ok: true, text: `added memory #${id}` };
      }
      case "forget": {
        const id = Number(String(a.id).replace(/[^0-9]/g, ""));
        const i = memories.findIndex((m) => m.id === id);
        if (i < 0) return { ok: false, error: `no active memory #${id}` };
        memories.splice(i, 1);
        return { ok: true, text: `forgot memory #${id}` };
      }
      case "access_status":
        return { ok: true, text: `${req.client?.name ?? "this app"} sees work only.` };
      default:
        return { ok: false, error: "unknown tool" };
    }
  };

  const server = createServer((sock) => {
    let buf = "";
    sock.setEncoding("utf8");
    sock.on("data", (chunk) => {
      buf += chunk;
      const nl = buf.indexOf("\n");
      if (nl < 0) return;
      const req = JSON.parse(buf.slice(0, nl));
      requests.push(req);
      if (mode === "slow") return; // never answers
      if (mode === "garbage") return sock.end("this is not json\n");
      if (mode === "huge") return sock.end(JSON.stringify({ ok: true, text: "x".repeat(2 * 1024 * 1024) }) + "\n");
      if (mode === "silent") return sock.end();
      sock.end(JSON.stringify(answer(req)) + "\n");
    });
    sock.on("error", () => {});
  });
  await new Promise((resolve) => server.listen(path, resolve));

  return {
    path,
    dir,
    requests,
    memories,
    close: () =>
      new Promise((resolve) =>
        server.close(() => {
          rmSync(dir, { recursive: true, force: true });
          resolve();
        }),
      ),
  };
}
