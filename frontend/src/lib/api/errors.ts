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

/**
 * The door's own answers (D-067), in plain words. The engine sends `message`
 * and `fix` with each, and those are shown first; these stand in if an
 * answer ever arrives without a sentence, so a refusal is never a raw code.
 */
const ACCESS_MESSAGES: Record<string, string> = {
  signed_out: "You are not signed in. Sign in with your Google account.",
  needs_onboarding: "Tell us who you are first. Fill in the short form.",
  awaiting_access: "Your access has not been set yet. Ask the admin to set it.",
  disabled: "Your access has been turned off. Ask the admin.",
  read_only: "Your access is read-only. Ask the admin for operator access to make changes.",
  admin_only: "Only an admin can see or change who has access.",
  sign_in_off: "Sign-in is not switched on for this engine yet.",
};

/** The engine said the person is not signed in: the session is gone. */
export function isSignedOut(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401 && error.code === "signed_out";
}

/** One line for a toast. Errors say what happened; they never apologise. */
export function describeError(error: unknown): string {
  if (error instanceof EngineUnreachableError) {
    return "Couldn't reach the engine. Start it, then try again.";
  }
  if (error instanceof ApiError) {
    if (error.message) return error.fix ? `${error.message} ${error.fix}` : error.message;
    return ACCESS_MESSAGES[error.code] ?? `The engine answered with status ${error.status}.`;
  }
  if (error instanceof Error && error.message) return error.message;
  return "Something went wrong talking to the engine.";
}
