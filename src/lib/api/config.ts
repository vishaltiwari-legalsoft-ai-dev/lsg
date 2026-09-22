/**
 * Where the engine lives. Both values are inlined at build time — they are
 * public by nature (NEXT_PUBLIC_*). Never put a key or credential here:
 * anything in this bundle ships to the browser.
 */
export type ApiMode = "api" | "fixtures";

// Default "" = same origin: the browser calls /api/* on this app, and next.config.ts
// rewrites it to the engine. No CORS, and the app runs on any port. Set
// NEXT_PUBLIC_API_BASE only to talk to an engine directly.
export const API_BASE: string = (process.env.NEXT_PUBLIC_API_BASE ?? "").replace(/\/+$/, "");

export const API_MODE: ApiMode =
  process.env.NEXT_PUBLIC_API_MODE === "fixtures" ? "fixtures" : "api";

/**
 * The command that starts the engine's API, shown when it can't be reached.
 * Through the interpreter: Windows Application Control blocks the venv's
 * launcher stubs on this machine, so `uv run lge serve` fails there.
 */
export const ENGINE_START_COMMAND = ".venv\\Scripts\\python.exe -m lge serve";
