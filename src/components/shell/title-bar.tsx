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
      className="flex h-9 w-60 items-center gap-2 rounded-control border border-rule bg-paper pr-1.5 pl-3 text-table text-slate transition-colors hover:border-rule-strong hover:bg-sheet hover:text-ink max-lg:w-9 max-lg:justify-center max-lg:px-0"
      aria-keyshortcuts="Control+K Meta+K"
      aria-label="Search firms"
    >
      <SearchIcon className="size-3.5 shrink-0" aria-hidden="true" />
      <span className="flex-1 text-left max-lg:hidden">Search firms</span>
      <span className="flex gap-0.5 max-lg:hidden" aria-hidden="true">
        <Kbd>{mod}</Kbd>
        <Kbd>K</Kbd>
      </span>
    </button>
  );
}

/** A still, inline placeholder for a title whose data is on its way. */
export function TitlePlaceholder() {
  return (
    <span aria-hidden="true" className="inline-block h-6 w-72 rounded-control bg-paper align-middle" />
  );
}

/**
 * The head of each sheet: the screen's name set narrow and heavy (the
 * wordmark's voice), what it is showing, its actions, and search. A firm's
 * own page sets the firm's name as a caption instead -- the record's title.
 */
export function TitleBar({
  title,
  meta,
  actions,
  caption = false,
  className,
}: {
  title: React.ReactNode;
  meta?: React.ReactNode;
  actions?: React.ReactNode;
  /** The title is a firm's name: set it in Caslon, as the caption of its record. */
  caption?: boolean;
  className?: string;
}) {
  return (
    <header
      className={cn(
        "flex min-h-(--titlebar-height) shrink-0 flex-wrap items-center justify-between gap-x-6 gap-y-3 border-b border-rule px-8 py-4 max-md:px-4",
        className,
      )}
    >
      <div className="flex min-w-0 flex-wrap items-baseline gap-x-4 gap-y-1">
        <h1
          className={cn(
            "min-w-0 text-ink",
            caption
              ? "caption text-caption-sm max-md:text-subtitle"
              : "type-narrow truncate text-title font-semibold tracking-[-0.01em]",
          )}
        >
          {title}
        </h1>
        {meta ? <div className="min-w-0 truncate text-body text-slate">{meta}</div> : null}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {actions}
        <SearchTrigger />
      </div>
    </header>
  );
}
