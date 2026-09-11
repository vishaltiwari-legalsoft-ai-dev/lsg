import type { ApiErrorBody } from "./types";

/** The engine answered, with the contract's error envelope. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly fix: string | null;

  constructor(status: number, code: string, message: string, fix: string | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.fix = fix;
  }
}

/** Nothing answered: the API process isn't running or isn't reachable. */
export class EngineUnreachableError extends Error {
  constructor(cause?: unknown) {
    super("Couldn't reach the engine.", { cause });
    this.name = "EngineUnreachableError";
  }
}

export function isApiErrorBody(value: unknown): value is ApiErrorBody {
  if (typeof value !== "object" || value === null || !("error" in value)) return false;
  const error = (value as { error: unknown }).error;
  return (
    typeof error === "object" &&
    error !== null &&
    typeof (error as { message?: unknown }).message === "string"
  );
}

/** One line for a toast. Errors say what happened; they never apologise. */
export function describeError(error: unknown): string {
  if (error instanceof EngineUnreachableError) {
    return "Couldn't reach the engine. Start it, then try again.";
  }
  if (error instanceof ApiError) {
    return error.fix ? `${error.message} ${error.fix}` : error.message;
  }
  if (error instanceof Error && error.message) return error.message;
  return "Something went wrong talking to the engine.";
}
