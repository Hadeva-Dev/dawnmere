// The one place the connector talks to the Wayfern app: one JSON line out, one back (docs/PROTOCOL.md).
import { lstatSync } from "node:fs";
import { createConnection } from "node:net";
import { ENV, NOT_RUNNING, PROTOCOL, VERSION, defaultSocket } from "./brand.js";

export const MAX_REPLY = 1024 * 1024;
const DEFAULT_TIMEOUT = 15000;

export type Client = { name: string | null; key: string | null; hint: string | null };
export type Reply = { ok: true; text: string } | { ok: false; error: string };

export function socketPath(env = process.env): string | null {
  return env[ENV.socket] || defaultSocket();
}

function timeoutMs(env = process.env): number {
  const n = Number(env[ENV.timeout]);
  return Number.isFinite(n) && n > 0 ? Math.min(n, 120000) : DEFAULT_TIMEOUT;
}

/** The socket only if it is one, and the user running the connector owns it: never another user's planted file. */
function usable(path: string): boolean {
  try {
    const st = lstatSync(path);
    return st.isSocket() && (typeof process.getuid !== "function" || st.uid === process.getuid());
  } catch {
    return false;
  }
}

export function ask(tool: string, args: Record<string, unknown>, client: Client, env = process.env): Promise<Reply> {
  const path = socketPath(env);
  if (!path || !usable(path)) return Promise.resolve({ ok: false, error: NOT_RUNNING });
  const line = JSON.stringify({ protocol: PROTOCOL, tool, args, client: { ...client, connector: VERSION } }) + "\n";

  return new Promise((resolve) => {
    let buf = "";
    let done = false;
    const sock = createConnection(path);
    const finish = (r: Reply) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      sock.destroy();
      resolve(r);
    };
    const timer = setTimeout(
      () => finish({ ok: false, error: "Wayfern took too long to answer. Try again in a moment." }),
      timeoutMs(env),
    );
    sock.setEncoding("utf8");
    sock.on("connect", () => sock.write(line));
    sock.on("data", (chunk: string) => {
      buf += chunk;
      if (buf.length > MAX_REPLY) return finish({ ok: false, error: "Wayfern's answer was too large." });
      const nl = buf.indexOf("\n");
      if (nl >= 0) finish(parse(buf.slice(0, nl)));
    });
    sock.on("end", () => finish(buf.trim() ? parse(buf) : { ok: false, error: "Wayfern closed without answering." }));
    sock.on("error", () => finish({ ok: false, error: NOT_RUNNING }));
  });
}

function parse(text: string): Reply {
  let v: unknown;
  try {
    v = JSON.parse(text);
  } catch {
    return { ok: false, error: "Wayfern sent an answer this connector can't read. Update both to the latest version." };
  }
  if (v && typeof v === "object") {
    const r = v as Record<string, unknown>;
    if (r.ok === true && typeof r.text === "string") return { ok: true, text: r.text };
    if (r.ok === false && typeof r.error === "string") return { ok: false, error: r.error };
  }
  return { ok: false, error: "Wayfern sent an answer this connector can't read. Update both to the latest version." };
}
