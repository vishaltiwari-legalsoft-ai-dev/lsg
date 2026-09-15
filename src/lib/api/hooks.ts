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
  BatchRequest,
  ContactCreate,
  ContactPatch,
  DecisionRequest,
  FirmsQuery,
  HandcheckDecision,
  HandcheckResponse,
  LeadDetail,
  LeadsQuery,
  OutcomeRequest,
} from "./types";

/** Every server-owned input sits in the key, so filters never share a cache entry. */
export const queryKeys = {
  health: ["health"] as const,
  today: ["today"] as const,
  overview: ["overview"] as const,
  leads: (filters: Omit<LeadsQuery, "cursor">) => ["leads", filters] as const,
  lead: (id: string) => ["lead", id] as const,
  drafts: (id: string) => ["drafts", id] as const,
  firms: (query: Omit<FirmsQuery, "cursor">) => ["firms", query] as const,
  firmSearch: (q: string) => ["firm-search", q] as const,
  firm: (id: string) => ["firm", id] as const,
  handcheck: ["handcheck"] as const,
  imports: ["imports"] as const,
  import: (id: string) => ["import", id] as const,
  job: (id: string) => ["job", id] as const,
  firmJobs: (firmId: string) => ["firm-jobs", firmId] as const,
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

/** The home page's numbers; refreshed every half minute while a job runs. */
export function useOverview() {
  return useQuery({
    queryKey: queryKeys.overview,
    queryFn: ({ signal }) => api.overview(signal),
    refetchInterval: (query) => (query.state.data?.running.length ? 5000 : 30_000),
  });
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

// ── Imports ─────────────────────────────────────────────────────────────────

export function useImports() {
  return useQuery({ queryKey: queryKeys.imports, queryFn: ({ signal }) => api.imports(signal) });
}

/** One sheet; polls while the engine is loading its batches. */
export function useImport(id: string | null) {
  return useQuery({
    queryKey: queryKeys.import(id ?? ""),
    queryFn: ({ signal }) => api.importDetail(id!, signal),
    enabled: Boolean(id),
    refetchInterval: (query) => (query.state.data?.status === "loading" ? 2000 : false),
  });
}

export function useUploadImport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ file, batchSize }: { file: File; batchSize: number }) =>
      api.uploadImport(file, batchSize),
    onSuccess: (detail) => {
      qc.setQueryData(queryKeys.import(detail.id), detail);
      void qc.invalidateQueries({ queryKey: queryKeys.imports });
      toast.success(`Read ${detail.row_count} rows from ${detail.file_name}.`);
    },
    onError: (error) => {
      toast.error(describeError(error));
    },
  });
}

/** A person's correction to how a column was read. */
export function useUpdateMapping(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (overrides: Record<string, string | null>) =>
      api.updateImportMapping(id, { overrides }),
    onSuccess: (detail) => {
      qc.setQueryData(queryKeys.import(id), detail);
      void qc.invalidateQueries({ queryKey: queryKeys.imports });
    },
    onError: (error) => {
      toast.error(describeError(error));
    },
  });
}

export function useStartLoad(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.startImportLoad(id),
    onSuccess: (response) => {
      toast(response.message);
      void qc.invalidateQueries({ queryKey: queryKeys.import(id) });
      void qc.invalidateQueries({ queryKey: queryKeys.imports });
    },
    onError: (error) => {
      toast.error(describeError(error));
    },
  });
}

// ── Actions: the user can act ───────────────────────────────────────────────

/** Everything a lead's detail depends on, after a change to it. */
function useLeadRefresh() {
  const qc = useQueryClient();
  return (leadId: string | null | undefined, firmId?: string | null) => {
    if (leadId) {
      void qc.invalidateQueries({ queryKey: queryKeys.lead(leadId) });
      void qc.invalidateQueries({ queryKey: queryKeys.drafts(leadId) });
    }
    if (firmId) {
      void qc.invalidateQueries({ queryKey: queryKeys.firm(firmId) });
      void qc.invalidateQueries({ queryKey: queryKeys.firmJobs(firmId) });
    }
    void qc.invalidateQueries({ queryKey: ["leads"] });
    void qc.invalidateQueries({ queryKey: queryKeys.today });
    void qc.invalidateQueries({ queryKey: queryKeys.overview });
  };
}

/** A job's progress; polls every two seconds while it is queued or running. */
export function useJob(id: string | null) {
  return useQuery({
    queryKey: queryKeys.job(id ?? ""),
    queryFn: ({ signal }) => api.job(id!, signal),
    enabled: Boolean(id),
    refetchInterval: (query) => {
      const status = query.state.data?.job.status;
      return status === "queued" || status === "running" ? 2000 : false;
    },
  });
}

/** A firm's recent research jobs; polls while one is queued or running. */
export function useFirmJobs(firmId: string) {
  return useQuery({
    queryKey: queryKeys.firmJobs(firmId),
    queryFn: ({ signal }) => api.firmJobs(firmId, signal),
    refetchInterval: (query) =>
      query.state.data?.items.some((j) => j.status === "queued" || j.status === "running")
        ? 2000
        : false,
  });
}

/** Research a firm now: the whole site, or only its people and addresses. */
export function useResearch(firmId: string, leadId?: string | null) {
  const qc = useQueryClient();
  const refresh = useLeadRefresh();
  return useMutation({
    mutationFn: (scope: "full" | "contacts") => api.research(firmId, scope),
    onSuccess: (response) => {
      qc.setQueryData(queryKeys.job(response.job.id), response);
      toast(
        response.job.kind === "research"
          ? "Researching the site now. Progress shows below."
          : "Looking for people and addresses now. Progress shows below.",
      );
      refresh(leadId, firmId);
    },
    onError: (error) => {
      toast.error(describeError(error));
    },
  });
}

/** Qualify, disqualify, hold, reopen, hand off. The toast is the API's message. */
export function useDecide(leadId: string) {
  const qc = useQueryClient();
  const refresh = useLeadRefresh();
  return useMutation({
    mutationFn: (request: DecisionRequest) => api.decide(leadId, request),
    onSuccess: (response) => {
      qc.setQueryData(queryKeys.lead(leadId), response.lead);
      toast.success(response.message);
      refresh(leadId, response.lead.firm.id);
    },
    onError: (error) => {
      toast.error(describeError(error));
    },
  });
}

export function useAddNote(leadId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (text: string) => api.addNote(leadId, text),
    onSuccess: (lead) => {
      qc.setQueryData(queryKeys.lead(leadId), lead);
    },
    onError: (error) => {
      toast.error(describeError(error));
    },
  });
}

export function useSetOwner(leadId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (owner: string | null) => api.setOwner(leadId, owner),
    onSuccess: (lead) => {
      qc.setQueryData(queryKeys.lead(leadId), lead);
      toast.success(lead.owner ? `Assigned to ${lead.owner}.` : "Unassigned.");
      void qc.invalidateQueries({ queryKey: ["leads"] });
    },
    onError: (error) => {
      toast.error(describeError(error));
    },
  });
}

/** Add, correct or strike out a person; choose the lead's primary contact. */
export function useContactEdits(firmId: string, leadId?: string | null) {
  const qc = useQueryClient();
  const refresh = useLeadRefresh();
  const onError = (error: unknown) => {
    toast.error(describeError(error));
  };
  const done = (message: string) => {
    toast.success(message);
    refresh(leadId, firmId);
  };
  const add = useMutation({
    mutationFn: (body: ContactCreate) => api.addContact(firmId, body),
    onSuccess: (r) => done(`Added ${r.contact.full_name}.`),
    onError,
  });
  const patch = useMutation({
    mutationFn: ({ contactId, body }: { contactId: string; body: ContactPatch }) =>
      api.patchContact(contactId, body),
    onSuccess: (r) => done(`Saved ${r.contact.full_name}.`),
    onError,
  });
  const remove = useMutation({
    mutationFn: ({ contactId, reason }: { contactId: string; reason?: string }) =>
      api.removeContact(contactId, reason),
    onSuccess: (r) => done(`Struck out ${r.contact.full_name}.`),
    onError,
  });
  const setPrimary = useMutation({
    mutationFn: (contactId: string) => api.setPrimaryContact(leadId!, contactId),
    onSuccess: (lead: LeadDetail) => {
      qc.setQueryData(queryKeys.lead(lead.id), lead);
      toast.success(`${lead.contact?.full_name ?? "Contact"} is now the primary contact.`);
      void qc.invalidateQueries({ queryKey: ["leads"] });
    },
    onError,
  });
  return { add, patch, remove, setPrimary };
}

/** The same decision, research or owner for many leads at once. */
export function useBatch() {
  const refresh = useLeadRefresh();
  return useMutation({
    mutationFn: (body: BatchRequest) => api.batch(body),
    onSuccess: (response, body) => {
      const ok = response.results.filter((r) => r.ok).length;
      const failed = response.results.length - ok;
      if (failed === 0) toast.success(`Done for ${ok} lead${ok === 1 ? "" : "s"}.`);
      else {
        const first = response.results.find((r) => !r.ok);
        toast(`Done for ${ok}, not for ${failed}: ${first?.message ?? ""}`);
      }
      for (const id of body.lead_ids) refresh(id);
    },
    onError: (error) => {
      toast.error(describeError(error));
    },
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
