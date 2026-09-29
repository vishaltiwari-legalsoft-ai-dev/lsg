"use client";

import { SectionHeading } from "@/components/layout/panel";
import { ErrorState } from "@/components/states/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useCapabilities } from "@/lib/api/hooks";
import type { CapabilityPart, CapabilityStep, OutsideService } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/**
 * What is built, what is half there, and what is still to come -- said by the
 * engine itself (GET /api/meta/capabilities), so the page cannot drift from
 * what the thing actually does. A built part whose outside service has no key
 * says so in its own line rather than looking finished.
 *
 * It is here for the walk-through a new person gets: the three steps of the
 * brief, in order, and then the three services the rest waits on.
 */
export function BuiltSoFar() {
  const capabilities = useCapabilities();

  if (capabilities.isPending) {
    return (
      <section aria-busy="true" aria-label="Loading what is built" className="grid gap-4">
        <Skeleton className="h-6 w-64" />
        <div className="grid gap-6 md:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-44" />
          ))}
        </div>
      </section>
    );
  }
  if (capabilities.isError) {
    return <ErrorState error={capabilities.error} onRetry={() => void capabilities.refetch()} />;
  }

  const data = capabilities.data;
  return (
    <section aria-labelledby="built-heading" className="grid gap-5">
      <SectionHeading id="built-heading">What is built, and what it still needs</SectionHeading>
      <p className="max-w-[74ch] text-body text-slate">{data.summary}</p>

      <ol className="grid border-y border-rule md:grid-cols-3 md:divide-x md:divide-rule">
        {data.steps.map((step) => (
          <StepColumn key={step.step} step={step} />
        ))}
      </ol>

      <div className="grid gap-3">
        <h3 className="text-section font-semibold text-ink">What it needs from outside</h3>
        <ul className="grid gap-4 md:grid-cols-3">
          {data.outside.map((service) => (
            <Service key={service.id} service={service} />
          ))}
        </ul>
      </div>
    </section>
  );
}

function StepColumn({ step }: { step: CapabilityStep }) {
  return (
    <li className="grid content-start gap-3 py-5 md:px-6 md:first:pl-0 md:last:pr-0">
      <div className="grid gap-1">
        <p className="flex items-baseline gap-2">
          <span className="type-narrow text-subtitle font-semibold text-cobalt tabular-nums">
            {step.step}
          </span>
          <span className="text-section font-semibold text-ink">{step.label}</span>
        </p>
        <p className="text-table text-slate">{step.note}</p>
      </div>
      <ul className="grid gap-2.5">
        {step.parts.map((part) => (
          <Part key={part.label} part={part} />
        ))}
      </ul>
    </li>
  );
}

const MARK: Record<CapabilityPart["state"], string> = {
  built: "border-ledger bg-ledger",
  partial: "border-slate bg-transparent",
  planned: "border-dashed border-rule-strong bg-transparent",
};

function Part({ part }: { part: CapabilityPart }) {
  return (
    <li className="grid grid-cols-[0.6rem_minmax(0,1fr)] items-start gap-x-2.5">
      <span
        aria-hidden="true"
        className={cn("mt-[0.45rem] size-2.5 rounded-full border", MARK[part.state])}
      />
      <span className="grid gap-0.5">
        <span className="text-table text-ink">
          {part.label}
          <span className="sr-only">: {part.state_display}</span>
        </span>
        {part.state !== "built" ? (
          <span className="text-meta text-slate">
            {part.state_display}
            {part.what ? `. ${part.what}` : ""}
          </span>
        ) : part.what ? (
          <span className="text-meta text-slate">{part.what}</span>
        ) : null}
        {part.waiting_on ? (
          <span className="text-meta text-redline">Idle until {part.waiting_on} is switched on</span>
        ) : null}
      </span>
    </li>
  );
}

function Service({ service }: { service: OutsideService }) {
  return (
    <li className="grid content-start gap-1.5 rounded-panel border border-rule px-4 py-3.5">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-body font-semibold text-ink">{service.label}</p>
        <span className={cn("text-meta", service.on ? "text-ledger" : "text-redline")}>
          {service.on ? "On" : "No key yet"}
        </span>
      </div>
      <p className="text-table text-slate">{service.what}</p>
      <p className="text-meta text-slate">
        {service.cost}
        {service.spent_display ? ` ${service.spent_display}.` : null}
      </p>
      <code className="text-meta text-slate">{service.key}</code>
    </li>
  );
}
