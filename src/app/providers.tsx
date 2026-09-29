"use client";

import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

import { CommandPaletteProvider } from "@/components/shell/command-palette";
import { Toaster } from "@/components/ui/sonner";
import { queryKeys } from "@/lib/api/hooks";
import { ApiError, isSignedOut } from "@/lib/api/errors";

function makeClient() {
  const client: QueryClient = new QueryClient({
    // A session can end while a screen is open (thirty days of use, or the
    // admin turned the person off). The first answer that says "signed out"
    // asks the engine who is asking again, and the gate shows the sign-in
    // screen instead of every screen failing on its own.
    queryCache: new QueryCache({
      onError: (error, query) => {
        if (isSignedOut(error) && query.queryKey[0] !== "auth") {
          void client.invalidateQueries({ queryKey: queryKeys.auth });
        }
      },
    }),
    mutationCache: new MutationCache({
      onError: (error) => {
        if (isSignedOut(error)) void client.invalidateQueries({ queryKey: queryKeys.auth });
      },
    }),
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
  return client;
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
