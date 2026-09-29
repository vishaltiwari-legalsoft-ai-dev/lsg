"use client";

import { ErrorState } from "@/components/states/error-state";

export default function RouteError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="px-8 py-10">
      <ErrorState error={error} onRetry={reset} />
    </div>
  );
}
