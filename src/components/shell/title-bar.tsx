"use client";

import { SearchIcon } from "lucide-react";
import { useSyncExternalStore } from "react";

import { Kbd } from "@/components/ui/kbd";
import { cn } from "@/lib/utils";
import { useCommandPalette } from "./command-palette";

const isMac = () => /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

function useModifierLabel() {
  return useSyncExternalStore(
    () => () => {},
    () => (isMac() ? "⌘" : "Ctrl"),
    () => "Ctrl",
  );
}

function SearchTrigger() {
  const { open } = useCommandPalette();
  const mod = useModifierLabel();
  return (
    <button
      type="button"
      onClick={open}
      className="flex h-8 w-64 items-center gap-2 rounded-control border border-rule bg-sheet pr-1.5 pl-2.5 text-table text-slate transition-colors hover:border-rule-strong hover:text-ink"
      aria-keyshortcuts="Control+K Meta+K"
    >
      <SearchIcon className="size-3.5 shrink-0" aria-hidden="true" />
      <span className="flex-1 text-left">Search firms</span>
      <span className="flex gap-0.5" aria-hidden="true">
        <Kbd>{mod}</Kbd>
        <Kbd>K</Kbd>
      </span>
    </button>
  );
}

/** A still, inline placeholder for a title whose data is on its way. */
export function TitlePlaceholder() {
  return (
    <span aria-hidden="true" className="inline-block h-5 w-72 rounded-control bg-rule/55 align-middle" />
  );
}

/** Each page's title bar: the page name, what it's showing, and ⌘K. */
export function TitleBar({
  title,
  meta,
  actions,
  className,
}: {
  title: React.ReactNode;
  meta?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn(
        "flex h-(--titlebar-height) shrink-0 items-center justify-between gap-6 border-b border-rule px-8",
        className,
      )}
    >
      <div className="flex min-w-0 items-baseline gap-3">
        <h1 className="truncate text-title font-medium text-ink">{title}</h1>
        {meta ? <div className="truncate text-body text-slate">{meta}</div> : null}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {actions}
        <SearchTrigger />
      </div>
    </header>
  );
}
