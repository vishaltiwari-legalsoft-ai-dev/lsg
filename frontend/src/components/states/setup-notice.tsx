"use client";

import Link from "next/link";
import { useSyncExternalStore } from "react";

import { useOverview } from "@/lib/api/hooks";

const noop = () => () => {};

/**
 * False on the server and through hydration, true after. The notice reads a
 * query the rail starts; a screen under a Suspense boundary hydrates after the
 * rail, by which time that query may have answered -- rendering the notice
 * then would not match the server's empty HTML.
 */
function useHydrated(): boolean {
  return useSyncExternalStore(noop, () => true, () => false);
}

/**
 * What each switched-off provider stops, and how to switch it on. Keyed by
 * the engine's own words for it (GET /api/today's attention.providers_inert).
 */
const WHAT_IT_STOPS: Record<string, string> = {
  "Email verification":
    "Address checking is off, so no lead can be ready to hand over. Add a NeverBounce or ZeroBounce key to the engine's settings file and restart the engine.",
  "Google Business Profile lookup":
    "The Google Business Profile lookup is off, so ratings and reviews come only from search snippets. Add a Serper key to the engine's settings file and restart the engine.",
  "AI extraction":
    "The AI is off, so sheets are read by rules alone and sites without the AI's reading. Add an OpenRouter key to the engine's settings file and restart the engine.",
};

/**
 * A setup notice: a provider the engine needs is switched off, and what that
 * stops. Shown where its absence would otherwise look like a fault -- an
 * Actual leads screen that can never show a ready lead says why.
 */
export function SetupNotice({ only }: { only?: string[] }) {
  const overview = useOverview();
  const hydrated = useHydrated();
  const inert = overview.data?.attention.providers_inert ?? [];
  const shown = inert.filter((p) => !only || only.includes(p));
  if (!hydrated || shown.length === 0) return null;
  return (
    <div role="note" className="grid gap-2 rounded-r-control border-l-2 border-cobalt bg-paper px-4 py-3">
      {shown.map((p) => (
        <p key={p} className="max-w-[80ch] text-body text-ink">
          {WHAT_IT_STOPS[p] ?? `${p} is off until its key is set in the engine's settings file.`}
        </p>
      ))}
      <Link href="/#faq" className="text-table text-cobalt hover:underline">
        Which keys the engine needs
      </Link>
    </div>
  );
}
