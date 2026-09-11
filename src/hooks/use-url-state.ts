"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { useCallback } from "react";

type Patch = Record<string, string | null | undefined>;

/**
 * Search params as screen state. Writes go through history.replaceState,
 * which the App Router syncs into useSearchParams — so moving through the
 * docket with j/k updates `?lead=` without a server round-trip or a new
 * history entry per keypress.
 */
export function useUrlState() {
  const params = useSearchParams();
  const pathname = usePathname();

  const update = useCallback(
    (patch: Patch, mode: "replace" | "push" = "replace") => {
      const next = new URLSearchParams(window.location.search);
      for (const [key, value] of Object.entries(patch)) {
        if (value === null || value === undefined || value === "") next.delete(key);
        else next.set(key, value);
      }
      const search = next.toString();
      const url = search ? `${pathname}?${search}` : pathname;
      if (mode === "push") window.history.pushState(null, "", url);
      else window.history.replaceState(null, "", url);
    },
    [pathname],
  );

  return { params, update };
}
