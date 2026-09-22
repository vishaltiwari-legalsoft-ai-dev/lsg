"use client";

import { API_MODE } from "@/lib/api/config";
import { useHealth } from "@/lib/api/hooks";
import { cn } from "@/lib/utils";

function Dot({ tone }: { tone: "ok" | "wait" | "down" | "sample" }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "mt-[5px] size-2 shrink-0 rounded-full",
        tone === "ok" && "bg-ledger",
        tone === "wait" && "bg-slate/50",
        tone === "down" && "bg-redline",
        tone === "sample" && "border border-dashed border-slate bg-transparent",
      )}
    />
  );
}

/**
 * Whether the screens are showing the engine's data -- and, in fixture mode,
 * a plain statement that they are not, so nobody mistakes sample leads for
 * real ones.
 */
export function EngineStatus() {
  const health = useHealth();

  let tone: "ok" | "wait" | "down" | "sample";
  let line: string;
  let detail: string | null = null;
  if (API_MODE === "fixtures") {
    tone = "sample";
    line = "Sample data";
    detail = "Not the live engine";
  } else if (health.isPending) {
    tone = "wait";
    line = "Checking the engine…";
  } else if (health.isError || health.data?.db === "down") {
    tone = "down";
    line = health.isError ? "Engine not reachable" : "Engine up, database down";
  } else {
    tone = "ok";
    line = "Engine connected";
    detail = `Version ${health.data.version}`;
  }

  return (
    <p className={cn("flex gap-2 text-meta", tone === "down" ? "text-redline" : "text-slate")}>
      <Dot tone={tone} />
      <span>
        <span className={cn("block", tone === "down" ? "text-redline" : "text-ink/80")}>{line}</span>
        {detail ? <span className="block tabular-nums">{detail}</span> : null}
      </span>
    </p>
  );
}
