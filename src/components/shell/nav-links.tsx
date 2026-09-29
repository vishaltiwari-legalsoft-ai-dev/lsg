"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useAuth, useOverview } from "@/lib/api/hooks";
import { formatCount } from "@/lib/format";
import { cn } from "@/lib/utils";
import { isActive, NAV_ACCOUNT, NAV_HOME, NAV_STEPS, showsAccount, type NavItem } from "./nav";

/** How many things wait for a person on this screen -- only where something can wait. */
function useWaiting(): Record<string, number | undefined> {
  const overview = useOverview();
  const stages = overview.data?.stages;
  const queue = stages
    ? stages
        .filter((s) => s.stage === "needs_review" || s.stage === "needs_contact" || s.stage === "replied")
        .reduce((n, s) => n + s.count, 0)
    : undefined;
  // The accuracy check's own count is 50 minus what was checked, so it reads
  // "50 waiting" on an empty store; it has no count until the engine caps it.
  return { "/leads": queue };
}

function RailLink({ item, count, indent }: { item: NavItem; count?: number; indent?: boolean }) {
  const pathname = usePathname();
  const active = isActive(pathname, item.href);
  return (
    <Link
      href={item.href}
      title={item.hint}
      aria-current={active ? "page" : undefined}
      className={cn(
        "binder-tab flex h-9 items-center justify-between gap-2 pr-4 text-body transition-colors duration-100",
        indent ? "pl-[42px]" : "pl-4",
        "max-md:h-8 max-md:rounded-control max-md:px-2.5 max-md:whitespace-nowrap",
        active
          ? "font-medium text-ink max-md:bg-sheet"
          : "rounded-l-[10px] text-ink/72 hover:bg-sheet/45 hover:text-ink",
      )}
    >
      <span className="truncate">{item.label}</span>
      {count !== undefined && count > 0 ? (
        <span className={cn("text-meta tabular-nums", active ? "text-cobalt" : "text-slate")}>
          <span className="sr-only">, </span>
          {formatCount(count)}
          <span className="sr-only"> waiting</span>
        </span>
      ) : null}
    </Link>
  );
}

/**
 * The rail's navigation: Home, then the three steps of the brief, each with
 * the screens where it is worked. The numerals are a real sequence -- a
 * sheet comes in, it is enriched, it is handed over.
 */
export function NavLinks() {
  const waiting = useWaiting();
  const auth = useAuth();
  const account = showsAccount(auth.data);
  return (
    <nav aria-label="Main" className="min-w-0">
      <ul className="grid gap-0.5 max-md:flex max-md:items-center max-md:gap-1 max-md:overflow-x-auto">
        <li>
          <RailLink item={NAV_HOME} />
        </li>
        {NAV_STEPS.map((step) => (
          <li key={step.step} className="md:pt-4 max-md:contents">
            <p
              id={`rail-step-${step.step}`}
              className="flex items-baseline gap-2.5 pb-1 pl-4 max-md:hidden"
            >
              <span aria-hidden="true" className="type-narrow w-4 text-[21px] leading-none font-semibold text-cobalt tabular-nums">
                {step.step}
              </span>
              <span className="text-meta font-semibold tracking-[0.01em] text-slate">
                <span className="sr-only">Step {step.step}: </span>
                {step.label}
              </span>
            </p>
            <ul aria-labelledby={`rail-step-${step.step}`} className="grid gap-0.5 max-md:contents">
              {step.items.map((item) => (
                <li key={item.href}>
                  <RailLink item={item} count={waiting[item.href]} indent />
                </li>
              ))}
            </ul>
          </li>
        ))}
        {account ? (
          <li className="md:pt-4 max-md:contents">
            <p id="rail-account" className="flex items-baseline gap-2.5 pb-1 pl-4 max-md:hidden">
              <span aria-hidden="true" className="w-4" />
              <span className="text-meta font-semibold tracking-[0.01em] text-slate">{NAV_ACCOUNT.label}</span>
            </p>
            <ul aria-labelledby="rail-account" className="grid gap-0.5 max-md:contents">
              {NAV_ACCOUNT.items.map((item) => (
                <li key={item.href}>
                  <RailLink item={item} indent />
                </li>
              ))}
            </ul>
          </li>
        ) : null}
      </ul>
    </nav>
  );
}
