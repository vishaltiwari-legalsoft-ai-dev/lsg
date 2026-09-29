"use client";

import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useMemo, useState } from "react";

import {
  Command,
  CommandDialog,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { useKeydown } from "@/hooks/use-keydown";
import { useAuth, useFirmSearch } from "@/lib/api/hooks";
import { formatPlace } from "@/lib/format";
import { navItemsFor } from "./nav";

interface PaletteContext {
  open: () => void;
}

const Ctx = createContext<PaletteContext>({ open: () => {} });

export function useCommandPalette() {
  return useContext(Ctx);
}

/**
 * ⌘K / Ctrl+K from anywhere: jump to a screen, or find a firm by name or
 * domain through /api/firms?q=. Results come from the engine, so the
 * palette's own filtering is off and screens are matched here.
 */
export function CommandPaletteProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const value = useMemo(() => ({ open: () => setOpen(true) }), []);

  useKeydown((event) => {
    if ((event.metaKey || event.ctrlKey) && !event.altKey && event.key.toLowerCase() === "k") {
      event.preventDefault();
      setOpen((o) => !o);
    }
  });

  return (
    <Ctx.Provider value={value}>
      {children}
      <CommandDialog
        open={open}
        onOpenChange={setOpen}
        title="Search"
        description="Jump to a screen or find a firm by name or domain."
      >
        {open ? <PaletteBody onDone={() => setOpen(false)} /> : null}
      </CommandDialog>
    </Ctx.Provider>
  );
}

function PaletteBody({ onDone }: { onDone: () => void }) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const term = query.trim();
  const search = useFirmSearch(term);
  // The gate has already answered this query; the palette only reads it, so
  // Users is listed for an admin and for nobody else.
  const auth = useAuth();

  const go = useCallback(
    (href: string) => {
      onDone();
      router.push(href);
    },
    [onDone, router],
  );

  const screens = navItemsFor(auth.data).filter(
    (item) => !term || item.label.toLowerCase().includes(term.toLowerCase()),
  );
  const firms = term.length >= 2 ? (search.data?.items ?? []) : [];
  const searching = term.length >= 2 && search.isFetching && firms.length === 0;

  return (
    <Command shouldFilter={false} loop label="Search">
      <CommandInput
        value={query}
        onValueChange={setQuery}
        placeholder="Search firms by name or domain, or jump to a screen"
      />
      <CommandList>
        {screens.length > 0 ? (
          <CommandGroup heading="Go to">
            {screens.map((item) => (
              <CommandItem key={item.href} value={`screen:${item.href}`} onSelect={() => go(item.href)}>
                <span className="flex-1">{item.label}</span>
                <span className="text-meta text-slate">{item.hint}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        ) : null}

        {term.length >= 2 ? (
          <CommandGroup heading="Firms">
            {search.isError ? (
              <p className="px-2.5 py-2 text-table text-redline">
                Couldn&apos;t search firms: the engine didn&apos;t answer.
              </p>
            ) : null}
            {searching ? <p className="px-2.5 py-2 text-table text-slate">Searching firms…</p> : null}
            {firms.map((firm) => (
              <CommandItem key={firm.id} value={`firm:${firm.id}`} onSelect={() => go(`/firms/${firm.id}`)}>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-ink">{firm.name}</span>
                  <span className="block truncate text-meta text-slate">
                    {[firm.domain, formatPlace(firm.city, firm.state)].filter(Boolean).join(", ")}
                  </span>
                </span>
                <span className="shrink-0 text-meta text-slate">{firm.tier_display}</span>
              </CommandItem>
            ))}
            {!searching && !search.isError && search.data && firms.length === 0 ? (
              <p className="px-2.5 py-2 text-table text-slate">
                No firm matches “{term}”. Try part of the name or the domain.
              </p>
            ) : null}
          </CommandGroup>
        ) : null}

        {term.length < 2 ? (
          <p className="px-2.5 pt-3 pb-1 text-meta text-slate">
            Type two letters or more to search firms by name or domain.
          </p>
        ) : null}
      </CommandList>
    </Command>
  );
}
