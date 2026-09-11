"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

import { CommandPaletteProvider } from "@/components/shell/command-palette";
import { Toaster } from "@/components/ui/sonner";
import { ApiError } from "@/lib/api/errors";

function makeClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: true,
        // A 4xx is an answer, not a blip; an unreachable engine should say so fast.
        retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 1,
        retryDelay: 400,
      },
    },
  });
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(makeClient);
  return (
    <QueryClientProvider client={client}>
      <CommandPaletteProvider>{children}</CommandPaletteProvider>
      <Toaster />
    </QueryClientProvider>
  );
}
