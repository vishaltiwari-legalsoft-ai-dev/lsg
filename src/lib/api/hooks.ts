"use client";

import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useMutationState,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useRef } from "react";
import { toast } from "sonner";

import { api } from "./client";
import { describeError } from "./errors";
import type {
  FirmsQuery,
  HandcheckDecision,
  HandcheckResponse,
  LeadsQuery,
  OutcomeRequest,
} from "./types";

/** Every server-owned input sits in the key, so filters never share a cache entry. */
export const queryKeys = {
  health: ["health"] as const,
  today: ["today"] as const,
  leads: (filters: Omit<LeadsQuery, "cursor">) => ["leads", filters] as const,
  lead: (id: string) => ["lead", id] as const,
  drafts: (id: string) => ["drafts", id] as const,
  firms: (query: Omit<FirmsQuery, "cursor">) => ["firms", query] as const,
  firmSearch: (q: string) => ["firm-search", q] as const,
  firm: (id: string) => ["firm", id] as const,
  handcheck: ["handcheck"] as const,
};

export const LEADS_PAGE_SIZE = 50;

export function useHealth() {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: ({ signal }) => api.health(signal),
    staleTime: 60_000,
    retry: false,
  });
}

export function useToday() {
  return useQuery({ queryKey: queryKeys.today, queryFn: ({ signal }) => api.today(signal) });
}

export function useLeads(filters: Omit<LeadsQuery, "cursor" | "limit">) {
  return useInfiniteQuery({
    queryKey: queryKeys.leads(filters),
    queryFn: ({ pageParam, signal }) =>
      api.leads({ ...filters, cursor: pageParam, limit: LEADS_PAGE_SIZE }, signal),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    // Instant filters: the previous list stays put while the next one loads.
    placeholderData: keepPreviousData,
  });
}

export function useLead(id: string | null) {
  return useQuery({
    queryKey: queryKeys.lead(id ?? ""),
    queryFn: ({ signal }) => api.lead(id!, signal),
    enabled: Boolean(id),
  });
}

export function useDrafts(id: string | null) {
  return useQuery({
    queryKey: queryKeys.drafts(id ?? ""),
    queryFn: ({ signal }) => api.drafts(id!, signal),
    enabled: Boolean(id),
  });
}

export const outcomeMutationKey = (leadId: string) => ["outcome", leadId] as const;

/**
 * Records an outcome. The toast is the API's `message`, verbatim — it is the
 * only place the person learns whether the lifecycle transition was applied.
 */
export function useRecordOutcome(leadId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationKey: outcomeMutationKey(leadId),
    mutationFn: (request: OutcomeRequest) => api.recordOutcome(leadId, request),
    onSuccess: (response) => {
      qc.setQueryData(queryKeys.lead(leadId), response.lead);
      if (response.transition_applied) toast.success(response.message);
      else toast(response.message);
      void qc.invalidateQueries({ queryKey: ["leads"] });
      void qc.invalidateQueries({ queryKey: queryKeys.today });
      void qc.invalidateQueries({ queryKey: queryKeys.drafts(leadId) });
    },
    onError: (error) => {
      toast.error(describeError(error));
    },
  });
}

/** Outcomes still in flight for a lead — rendered optimistically in its history. */
export function usePendingOutcomes(leadId: string): OutcomeRequest[] {
  return useMutationState({
    filters: { mutationKey: outcomeMutationKey(leadId), status: "pending" },
    select: (mutation) => mutation.state.variables as OutcomeRequest,
  });
}

export function useFirms(query: Omit<FirmsQuery, "cursor" | "limit">) {
  return useInfiniteQuery({
    queryKey: queryKeys.firms(query),
    queryFn: ({ pageParam, signal }) =>
      api.firms({ ...query, cursor: pageParam, limit: LEADS_PAGE_SIZE }, signal),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    placeholderData: keepPreviousData,
  });
}

/** The ⌘K palette's firm search: name or domain, from two characters. */
export function useFirmSearch(q: string) {
  const term = q.trim();
  return useQuery({
    queryKey: queryKeys.firmSearch(term),
    queryFn: ({ signal }) => api.firms({ q: term, limit: 8 }, signal),
    enabled: term.length >= 2,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}

export function useFirm(id: string) {
  return useQuery({ queryKey: queryKeys.firm(id), queryFn: ({ signal }) => api.firm(id, signal) });
}

export function useHandcheck() {
  return useQuery({
    queryKey: queryKeys.handcheck,
    queryFn: ({ signal }) => api.handcheck(signal),
  });
}

interface HandcheckVars {
  firmId: string;
  attr: string;
  decision: HandcheckDecision;
}

/**
 * A hand-check verdict. The review is shown at once; the gate and the
 * per-attribute accuracy are the engine's arithmetic, refetched once the
 * reviewer pauses rather than on every keystroke.
 */
export function useHandcheckDecision() {
  const qc = useQueryClient();
  const refresh = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  return useMutation({
    mutationFn: ({ firmId, attr, decision }: HandcheckVars) =>
      api.decideHandcheck(firmId, attr, decision),
    onMutate: async ({ firmId, attr, decision }) => {
      clearTimeout(refresh.current);
      await qc.cancelQueries({ queryKey: queryKeys.handcheck });
      const previous = qc.getQueryData<HandcheckResponse>(queryKeys.handcheck);
      if (previous) {
        qc.setQueryData<HandcheckResponse>(queryKeys.handcheck, {
          ...previous,
          sample: previous.sample.map((firm) =>
            firm.firm_id !== firmId
              ? firm
              : {
                  ...firm,
                  reviews: {
                    ...firm.reviews,
                    [attr]: {
                      correct: decision.correct,
                      corrected_value: decision.corrected_value ?? null,
                    },
                  },
                },
          ),
        });
      }
      return { previous };
    },
    onError: (error, _vars, context) => {
      if (context?.previous) qc.setQueryData(queryKeys.handcheck, context.previous);
      toast.error(describeError(error));
    },
    onSettled: () => {
      clearTimeout(refresh.current);
      refresh.current = setTimeout(() => {
        void qc.invalidateQueries({ queryKey: queryKeys.handcheck });
      }, 700);
    },
  });
}
