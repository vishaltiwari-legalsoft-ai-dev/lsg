"use client";

import { API_MODE } from "@/lib/api/config";
import { useHealth } from "@/lib/api/hooks";

/**
 * Whether the screens are showing the engine's data — and, in fixture mode,
 * a plain statement that they are not, so nobody mistakes sample leads for
 * real ones.
 */
export function EngineStatus() {
  const health = useHealth();

  if (API_MODE === "fixtures") {
    return (
      <p className="rounded-control border border-dashed border-slate/55 px-2.5 py-2 text-meta text-slate">
        Showing fixture data, not the live engine.
      </p>
    );
  }

  if (health.isPending) {
    return <p className="px-2.5 text-meta text-slate">Checking the engine…</p>;
  }

  if (health.isError || health.data?.db === "down") {
    return (
      <p className="px-2.5 text-meta text-redline">
        {health.isError ? "Engine not reachable" : "Engine up, database down"}
      </p>
    );
  }

  return (
    <p className="px-2.5 text-meta text-slate">
      Engine connected
      <span className="block tabular-nums">Version {health.data.version}</span>
    </p>
  );
}
