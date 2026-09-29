"use client";

import { ChevronRightIcon } from "lucide-react";
import { Fragment, useMemo, useState } from "react";

import { StatusBadge } from "@/components/record/status-badge";
import { TitleBar } from "@/components/shell/title-bar";
import { EmptyState } from "@/components/states/empty-state";
import { ErrorState } from "@/components/states/error-state";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api/errors";
import { useSetUserAccess, useUser, useUsers } from "@/lib/api/hooks";
import type { AssignableAccess, AuthUser, OnboardingField, UserOption, UsersResponse } from "@/lib/api/types";
import { formatCount, formatDateTime, relativeDays } from "@/lib/format";
import { cn } from "@/lib/utils";
import { answerText, eventWords, setByWords } from "./user-words";

/** The form's questions, for showing a person's answers by label. */
const ANSWER_LABELS: Pick<OnboardingField, "name" | "label">[] = [
  { name: "full_name", label: "Name" },
  { name: "title", label: "Role at Legal Soft" },
  { name: "team", label: "Team" },
  { name: "purpose", label: "What they will use the engine for" },
  { name: "phone", label: "Phone" },
];

/** Waiting people first, the engine's order kept within each group. */
export function waitingFirst(items: AuthUser[]): AuthUser[] {
  return [
    ...items.filter((u) => u.standing === "awaiting_access"),
    ...items.filter((u) => u.standing !== "awaiting_access"),
  ];
}

function UsersSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading who has signed in">
      {Array.from({ length: 5 }, (_, i) => (
        <div key={i} className="flex items-center gap-6 border-b border-rule py-3.5 last:border-b-0">
          <div className="grid w-[26%] gap-1.5">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-3 w-4/5" />
          </div>
          <Skeleton className="h-4 w-28" />
          <Skeleton className="h-4 flex-1" />
          <Skeleton className="h-4 w-20" />
          <Skeleton className="h-8 w-28" />
        </div>
      ))}
    </div>
  );
}

/** The refusals this screen expects, each in its own words; anything else is the error state. */
function UsersError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  if (error instanceof ApiError && error.code === "admin_only") {
    return (
      <EmptyState title="Only an admin can see this.">
        Who has signed in, and what each may do, is the admin&apos;s to decide.
      </EmptyState>
    );
  }
  if (error instanceof ApiError && error.code === "sign_in_off") {
    return (
      <EmptyState title="Sign-in is not switched on for this engine yet.">
        <p>
          Until it is, there is nobody to list. Set both of these in the engine&apos;s settings file and
          restart it:
        </p>
        <code className="mt-2 block rounded-[4px] border border-rule bg-paper px-2 py-1.5 font-mono text-[12.5px] text-ink">
          GOOGLE_OAUTH_CLIENT_ID GOOGLE_OAUTH_CLIENT_SECRET
        </code>
      </EmptyState>
    );
  }
  return (
    <div className="py-6">
      <ErrorState error={error} onRetry={onRetry} />
    </div>
  );
}

function Person({ user }: { user: AuthUser }) {
  return (
    <div className="flex min-w-0 items-center gap-3">
      {user.picture_url ? (
        // Google's own picture of them; a plain <img>, as the host is not ours to configure.
        // eslint-disable-next-line @next/next/no-img-element
        <img src={user.picture_url} alt="" width={28} height={28} className="size-7 shrink-0 rounded-full bg-paper" />
      ) : (
        <span aria-hidden="true" className="flex size-7 shrink-0 items-center justify-center rounded-full bg-paper text-meta font-medium text-slate">
          {(user.name ?? user.email).charAt(0).toUpperCase()}
        </span>
      )}
      <span className="min-w-0">
        <span className="block truncate text-ink">{user.name ?? user.email}</span>
        {user.name ? <span className="block truncate text-meta text-slate">{user.email}</span> : null}
      </span>
    </div>
  );
}

function AccessControl({
  user,
  levels,
  onChange,
  saving,
}: {
  user: AuthUser;
  levels: UserOption[];
  onChange: (access: AssignableAccess) => void;
  saving: boolean;
}) {
  if (user.admin_by_settings) {
    return (
      <span className="grid gap-0.5">
        <span className="text-ink">Admin</span>
        <span className="text-meta text-slate">Admin by the engine&apos;s settings</span>
      </span>
    );
  }
  // Pending is the state before a decision, never a choice: it shows as the
  // placeholder until the admin picks a level.
  const value = user.access === "pending" ? undefined : user.access;
  return (
    <Select value={value} onValueChange={(v) => onChange(v as AssignableAccess)} disabled={saving}>
      <SelectTrigger aria-label={`Access for ${user.name ?? user.email}`} className="h-8 w-36">
        <SelectValue placeholder="Choose a level" />
      </SelectTrigger>
      <SelectContent>
        {levels.map((level) => (
          <SelectItem key={level.value} value={level.value} hint={LEVEL_HINTS[level.value]}>
            {level.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

const LEVEL_HINTS: Record<string, string> = {
  admin: "Everything, including this screen",
  operator: "Works the leads, records decisions and edits",
  viewer: "Reads everything, changes nothing",
  disabled: "Turned off; their sessions close",
};

/** The full answers and the history, under the row. */
function UserDetailRow({ user, levels }: { user: AuthUser; levels: UserOption[] }) {
  const detail = useUser(user.id);
  const answers = ANSWER_LABELS.map((f) => [f.label, answerText(user, f.name)] as const).filter(([, v]) => v);
  return (
    <div className="grid gap-6 py-5 pl-11 md:grid-cols-2">
      <section aria-label="What they said on the form" className="grid content-start gap-3">
        <h3 className="text-meta font-semibold text-slate">What they said on the form</h3>
        {answers.length === 0 ? (
          <p className="text-table text-slate">
            {user.admin_by_settings ? "An admin by the engine's settings skips the form." : "Not filled in yet."}
          </p>
        ) : (
          <dl className="grid gap-2.5">
            {answers.map(([label, value]) => (
              <div key={label} className="grid gap-0.5">
                <dt className="text-meta text-slate">{label}</dt>
                <dd className="max-w-[60ch] text-table whitespace-pre-line text-ink">{value}</dd>
              </div>
            ))}
          </dl>
        )}
      </section>
      <section aria-label="History" className="grid content-start gap-3">
        <h3 className="text-meta font-semibold text-slate">History</h3>
        {detail.isPending ? (
          <div className="grid gap-2" aria-busy="true">
            <Skeleton className="h-3.5 w-3/5" />
            <Skeleton className="h-3.5 w-2/5" />
            <Skeleton className="h-3.5 w-1/2" />
          </div>
        ) : detail.isError ? (
          <ErrorState error={detail.error} onRetry={() => void detail.refetch()} />
        ) : detail.data.events.length === 0 ? (
          <p className="text-table text-slate">Nothing recorded yet.</p>
        ) : (
          <ol className="grid gap-2">
            {detail.data.events.map((event, i) => (
              <li key={`${event.at}-${i}`} className="grid grid-cols-[7.5rem_minmax(0,1fr)] gap-3 text-table">
                <time dateTime={event.at} className="text-slate tabular-nums">
                  {formatDateTime(event.at)}
                </time>
                <span className="text-ink">{eventWords(event, levels)}</span>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}

function UsersTable({ data }: { data: UsersResponse }) {
  const items = useMemo(() => waitingFirst(data.items), [data.items]);
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const setAccess = useSetUserAccess();
  const saving = setAccess.isPending ? setAccess.variables.id : null;

  function toggle(id: string) {
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[60rem] border-collapse text-left text-table">
        <caption className="sr-only">
          Everyone who has signed in, the ones waiting first. Open a row for their answers and history.
        </caption>
        <thead>
          <tr className="border-b border-rule text-meta text-slate">
            <th scope="col" className="h-10 w-[26%] font-medium">Person</th>
            <th scope="col" className="w-[15%] font-medium">Team and role</th>
            <th scope="col" className="font-medium">What they will use it for</th>
            <th scope="col" className="w-[11%] font-medium">Last sign-in</th>
            <th scope="col" className="w-[13%] font-medium">Access</th>
            <th scope="col" className="w-[15%] font-medium">Set by</th>
          </tr>
        </thead>
        <tbody>
          {items.map((user) => {
            const waiting = user.standing === "awaiting_access";
            const expanded = open.has(user.id);
            const team = answerText(user, "team");
            const title = answerText(user, "title");
            const purpose = answerText(user, "purpose");
            const setBy = setByWords(user.access_set_by);
            return (
              <Fragment key={user.id}>
                <tr
                  data-waiting={waiting || undefined}
                  className={cn(
                    "border-b border-rule align-top transition-colors duration-75",
                    expanded ? "border-b-0 bg-paper/60" : "hover:bg-paper",
                  )}
                >
                  <td className="py-3 pr-3">
                    <div className="flex items-start gap-1">
                      <button
                        type="button"
                        aria-expanded={expanded}
                        aria-label={`${expanded ? "Close" : "Open"} ${user.name ?? user.email}`}
                        onClick={() => toggle(user.id)}
                        className="mt-1 flex size-6 shrink-0 items-center justify-center rounded-control text-slate hover:bg-paper hover:text-ink"
                      >
                        <ChevronRightIcon
                          className={cn("size-3.5 transition-transform duration-100", expanded && "rotate-90")}
                          aria-hidden="true"
                        />
                      </button>
                      <div className="grid min-w-0 gap-1.5">
                        <Person user={user} />
                        {waiting ? (
                          <StatusBadge state="act" className="ml-10 w-fit">
                            Waiting for you
                          </StatusBadge>
                        ) : user.standing === "needs_onboarding" ? (
                          <StatusBadge state="no_data" className="ml-10 w-fit">
                            {user.standing_display ?? "Signed in, form not filled"}
                          </StatusBadge>
                        ) : user.standing === "disabled" ? (
                          <StatusBadge state="failure" className="ml-10 w-fit">
                            {user.standing_display ?? "Disabled"}
                          </StatusBadge>
                        ) : null}
                      </div>
                    </div>
                  </td>
                  <td className="py-3 pr-3 text-ink">
                    {team || title ? (
                      <span className="grid gap-0.5">
                        {team ? <span>{team}</span> : null}
                        {title ? <span className="text-meta text-slate">{title}</span> : null}
                      </span>
                    ) : (
                      <span className="text-slate">{user.admin_by_settings ? "The admin" : "Not filled in"}</span>
                    )}
                  </td>
                  <td className="py-3 pr-3 text-ink">
                    {purpose ? (
                      <span className={cn("block max-w-[52ch]", !expanded && "line-clamp-2")}>{purpose}</span>
                    ) : (
                      <span className="text-slate">{user.admin_by_settings ? "Runs the engine" : "Not filled in"}</span>
                    )}
                  </td>
                  <td className="py-3 pr-3 whitespace-nowrap text-ink">
                    {user.last_sign_in_at ? (
                      <time dateTime={user.last_sign_in_at} title={formatDateTime(user.last_sign_in_at)}>
                        {capital(relativeDays(user.last_sign_in_at))}
                      </time>
                    ) : (
                      <span className="text-slate">Never</span>
                    )}
                  </td>
                  <td className="py-2.5 pr-3">
                    <AccessControl
                      user={user}
                      levels={data.levels}
                      saving={saving === user.id}
                      onChange={(access) => setAccess.mutate({ id: user.id, access })}
                    />
                  </td>
                  <td className="py-3 text-ink">
                    {setBy ? (
                      <span className="grid gap-0.5">
                        <span className="truncate" title={setBy}>{setBy}</span>
                        {user.access_set_at ? (
                          <time dateTime={user.access_set_at} className="text-meta text-slate">
                            {formatDateTime(user.access_set_at)}
                          </time>
                        ) : null}
                      </span>
                    ) : (
                      <span className="text-slate">Not set yet</span>
                    )}
                  </td>
                </tr>
                {expanded ? (
                  <tr className="border-b border-rule bg-paper/60">
                    <td colSpan={6} className="p-0">
                      <UserDetailRow user={user} levels={data.levels} />
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function capital(words: string): string {
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function metaWords(data: UsersResponse): string {
  const people = data.items.length;
  const head = `${formatCount(people)} ${people === 1 ? "person has" : "people have"} signed in`;
  return data.waiting > 0 ? `${head}, ${formatCount(data.waiting)} waiting for you` : head;
}

/**
 * The Users screen (D-067). Admin only: everyone who has signed in, the ones
 * waiting first, what they said on the form, when they last signed in, and
 * who set their access. One control per person sets the level.
 */
export function UsersScreen() {
  const users = useUsers();
  return (
    <>
      <TitleBar title="Users" meta={users.data ? metaWords(users.data) : undefined} />
      <div className="grid max-w-[90rem] gap-5 px-8 pt-6 pb-16 max-md:px-4">
        <p className="max-w-[68ch] text-body text-slate">
          Anyone at Legal Soft can sign in with Google; they appear here once they have. Someone new waits
          until you set what they may do: an operator works the leads, a viewer only reads, an admin can
          do this too.
        </p>
        <section aria-label="Who has signed in" className="border-t border-rule">
          {users.isPending ? (
            <UsersSkeleton />
          ) : users.isError ? (
            <UsersError error={users.error} onRetry={() => void users.refetch()} />
          ) : users.data.items.length === 0 ? (
            <EmptyState title="Nobody else has signed in yet.">
              Anyone at legalsoft.com can sign in with Google; they appear here.
            </EmptyState>
          ) : (
            <UsersTable data={users.data} />
          )}
        </section>
      </div>
    </>
  );
}
