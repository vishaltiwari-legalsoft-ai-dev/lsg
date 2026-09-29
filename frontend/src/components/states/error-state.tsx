"use client";

import { Button } from "@/components/ui/button";
import { ENGINE_START_COMMAND } from "@/lib/api/config";
import { ApiError, EngineUnreachableError } from "@/lib/api/errors";
import { cn } from "@/lib/utils";

/**
 * Errors say what happened and how to fix it. They never apologise.
 * The redline rule marks it as a problem; the words carry the meaning.
 */
export function ErrorState({
  error,
  onRetry,
  className,
}: {
  error: unknown;
  onRetry?: () => void;
  className?: string;
}) {
  let title = "The engine returned something this screen can't read.";
  let fix: React.ReactNode = "Reload the page. If it keeps happening, check the engine's log.";

  if (error instanceof EngineUnreachableError) {
    title = "Couldn't reach the engine.";
    fix = (
      <>
        Start it with{" "}
        <code className="rounded-[4px] border border-rule bg-paper px-1.5 py-0.5 font-mono text-[12.5px] text-ink">
          {ENGINE_START_COMMAND}
        </code>{" "}
        in the backend folder, then reload.
      </>
    );
  } else if (error instanceof ApiError) {
    title = error.message;
    fix = error.fix ?? `The engine answered with status ${error.status}.`;
  }

  return (
    <div
      role="alert"
      className={cn("grid max-w-[64ch] justify-items-start gap-2 border-l-2 border-redline py-2 pl-4", className)}
    >
      <p className="text-section font-medium text-ink">{title}</p>
      <p className="text-body text-slate">{fix}</p>
      {onRetry ? (
        <Button variant="secondary" size="sm" className="mt-2" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}
