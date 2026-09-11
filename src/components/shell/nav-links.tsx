"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useToday } from "@/lib/api/hooks";
import { formatCount } from "@/lib/format";
import { cn } from "@/lib/utils";
import { isActive, NAV_ITEMS } from "./nav";

export function NavLinks() {
  const pathname = usePathname();
  const today = useToday();
  const handcheckWaiting = today.data?.attention.queues.handcheck;

  return (
    <nav aria-label="Main">
      <ul className="grid gap-0.5 max-md:flex max-md:overflow-x-auto">
        {NAV_ITEMS.map((item) => {
          const active = isActive(pathname, item.href);
          const count = item.href === "/review/handcheck" ? handcheckWaiting : undefined;
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex h-8 items-center justify-between gap-2 rounded-control px-2.5 text-body transition-colors",
                  active
                    ? "bg-cobalt-wash font-medium text-ink"
                    : "text-slate hover:bg-sheet hover:text-ink",
                )}
              >
                <span>{item.label}</span>
                {count !== undefined && count > 0 ? (
                  <span
                    className={cn(
                      "text-meta tabular-nums",
                      active ? "text-cobalt" : "text-slate",
                    )}
                  >
                    <span className="sr-only">, </span>
                    {formatCount(count)}
                    <span className="sr-only"> waiting</span>
                  </span>
                ) : null}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
