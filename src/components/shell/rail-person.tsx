"use client";

import { useAuth, useSignOut } from "@/lib/api/hooks";

/** The word for a level on the rail; the engine's own display when it sends one. */
function accessWord(access: string, display: string | null | undefined): string {
  if (display) return display;
  switch (access) {
    case "admin":
      return "Admin";
    case "operator":
      return "Operator";
    case "viewer":
      return "Viewer";
    default:
      return access;
  }
}

/**
 * The signed-in person at the foot of the rail (D-067): who, what they may
 * do, and the way out. Nothing shows while sign-in is off -- there is nobody
 * to name -- or while the engine is still saying who is asking.
 */
export function RailPerson() {
  const auth = useAuth();
  const signOut = useSignOut();
  const status = auth.data;
  if (!status || status.standing !== "active" || !status.user) return null;
  const user = status.user;
  return (
    <div className="grid gap-1 border-t border-desk-deep pt-3 text-meta">
      <p className="min-w-0">
        <span className="block truncate text-body text-ink" title={user.email}>
          {user.name ?? user.email}
        </span>
        {user.name ? (
          <span className="block truncate text-slate" title={user.email}>
            {user.email}
          </span>
        ) : null}
      </p>
      <p className="flex items-center justify-between gap-3">
        <span className="rounded-control border border-rule-strong bg-sheet px-1.5 py-px font-medium text-ink">
          {accessWord(user.access, user.access_display)}
          {user.access === "viewer" ? <span className="font-normal text-slate">, read-only</span> : null}
        </span>
        <button
          type="button"
          onClick={() => signOut.mutate()}
          disabled={signOut.isPending}
          className="rounded-[4px] text-cobalt underline-offset-3 hover:underline disabled:opacity-45"
        >
          {signOut.isPending ? "Signing out…" : "Sign out"}
        </button>
      </p>
    </div>
  );
}
