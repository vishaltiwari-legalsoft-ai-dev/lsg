/**
 * Where the engine lives. Both values are inlined at build time — they are
 * public by nature (NEXT_PUBLIC_*). Never put a key or credential here:
 * anything in this bundle ships to the browser.
 */
export type ApiMode = "api" | "fixtures";

export const API_BASE: string = (
  process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000"
).replace(/\/+$/, "");

export const API_MODE: ApiMode =
  process.env.NEXT_PUBLIC_API_MODE === "fixtures" ? "fixtures" : "api";

/** The command that starts the engine's API, shown when it can't be reached. */
export const ENGINE_START_COMMAND = "uv run lge serve";
