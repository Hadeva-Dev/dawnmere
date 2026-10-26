// The four tools. Each checks its arguments, then hands the call to the memory app unchanged (daemon.ts).
// Nothing here decides what an app may see: the app does, from who is asking.
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { ENV, INSTRUCTIONS, SERVER_NAME, VERSION } from "./brand.js";
import { ask, type Client } from "./daemon.js";

export function createServer(env = process.env): McpServer {
  const server = new McpServer({ name: SERVER_NAME, version: VERSION }, { instructions: INSTRUCTIONS });

  const client = (): Client => ({
    name: env[ENV.client] || null,
    key: env[ENV.key] || null,
    hint: server.server.getClientVersion()?.name ?? null,
  });

  const call = async (tool: string, args: Record<string, unknown>) => {
    const r = await ask(tool, args, client(), env);
    return r.ok
      ? { content: [{ type: "text" as const, text: r.text }] }
      : { content: [{ type: "text" as const, text: r.error }], isError: true };
  };

  server.registerTool(
    "recall",
    {
      title: "Recall from memory",
      description:
        "Use this when the answer may depend on something the user told you or another of their AI apps before: " +
        "their preferences, projects, decisions or people. Searches the user's memory by meaning and keywords.",
      inputSchema: {
        query: z.string().min(1).max(2000).describe("What to look for, in plain words."),
        k: z.number().int().min(1).max(20).optional().describe("How many memories at most (default 8)."),
        section: z.string().max(64).optional().describe("Keep one part of memory, if the user names one."),
      },
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    (args) => call("recall", args),
  );

  server.registerTool(
    "remember",
    {
      title: "Save to memory",
      description:
        "Use this when the user tells you something worth knowing in future conversations, in any of their AI " +
        "apps: who they are, a preference, a decision, a person, a pointer. One self-contained fact per call: a " +
        "first line that sums it up, then the detail. A near-duplicate updates the older memory.",
      inputSchema: {
        content: z.string().min(1).max(4000).describe("The fact, readable with no other context."),
        kind: z.enum(["user", "feedback", "project", "reference", "note"]).optional(),
        project: z.string().max(100).optional().describe("The project it belongs to, if any."),
      },
      annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: false },
    },
    (args) => call("remember", args),
  );

  server.registerTool(
    "forget",
    {
      title: "Forget a memory",
      description:
        "Use this when a memory recall showed is wrong, out of date, or the user asks you to forget it. " +
        "Retires that one memory; it can be restored later.",
      inputSchema: {
        id: z
          .union([z.number().int().min(0), z.string().regex(/^\s*[cC]?\d{1,9}\s*$/)])
          .describe("The memory's id exactly as recall showed it."),
      },
      annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: true, openWorldHint: false },
    },
    (args) => call("forget", args),
  );

  server.registerTool(
    "access_status",
    {
      title: "What this app can see",
      description:
        "Use this when the user asks what this app can see in their memory, or why something is hidden from it.",
      inputSchema: {},
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    () => call("access_status", {}),
  );

  return server;
}
