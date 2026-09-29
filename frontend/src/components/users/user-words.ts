import type { AuthUser, UserEvent, UserOption } from "@/lib/api/types";

/** The word for a level: the engine's label when it sent one, else the plainest. */
export function levelWord(value: unknown, levels: UserOption[]): string {
  const found = levels.find((l) => l.value === value);
  if (found) return found.label;
  switch (value) {
    case "admin":
      return "Admin";
    case "operator":
      return "Operator";
    case "viewer":
      return "Viewer";
    case "disabled":
      return "Disabled";
    case "pending":
      return "Waiting for access";
    default:
      return typeof value === "string" ? value.replaceAll("_", " ") : "unknown";
  }
}

/** Who set a person's access, in words: "the engine's settings" for `settings`. */
export function setByWords(by: string | null): string | null {
  if (!by) return null;
  return by === "settings" ? "the engine's settings" : by;
}

/**
 * One line for each thing that happened to a person's account, from the
 * engine's event kinds: "Signed up", "Filled the form", "Access set to
 * Viewer by vishal.tiwari@legalsoft.com". An unknown kind is still words.
 */
export function eventWords(event: UserEvent, levels: UserOption[]): string {
  const detail = event.detail ?? {};
  switch (event.kind) {
    case "signed_up":
      return detail.admin_by_settings === true
        ? "Signed up, an admin by the engine's settings"
        : "Signed up";
    case "signed_in":
      return "Signed in";
    case "onboarded":
      return "Filled the form";
    case "access_set": {
      const to = levelWord(detail.to, levels);
      const by = setByWords(typeof detail.by === "string" ? detail.by : null) ?? event.actor;
      return `Access set to ${to} by ${by}`;
    }
    default: {
      const words = event.kind.replaceAll("_", " ");
      return words.charAt(0).toUpperCase() + words.slice(1);
    }
  }
}

/** An onboarding answer as text; the admin's own row carries only a flag. */
export function answerText(user: AuthUser, name: string): string | null {
  const value = user.onboarding?.[name];
  if (typeof value !== "string") return null;
  const text = value.trim();
  return text || null;
}
