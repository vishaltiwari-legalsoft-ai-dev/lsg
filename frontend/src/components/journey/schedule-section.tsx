"use client";

import { useState } from "react";
import { toast } from "sonner";

import { SectionHeading } from "@/components/layout/panel";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { describeError } from "@/lib/api/errors";
import { useRestoreJourneyDays, useSaveJourneyDays } from "@/lib/api/hooks";
import type { JourneyResponse } from "@/lib/api/types";
import { dayLabel, dayProblems } from "@/lib/journey";

/**
 * The nine emails and the day each one goes, as the sequence sends them.
 * "Change the days" turns each day into a field; the whole schedule is saved
 * at once, so an order that does not work is caught before it is saved.
 */
export function ScheduleSection({ journey }: { journey: JourneyResponse }) {
  const [editing, setEditing] = useState(false);
  const edited = journey.steps.some((s) => s.day !== s.original_day);

  return (
    <section aria-labelledby="schedule-heading" className="grid gap-3">
      <SectionHeading
        id="schedule-heading"
        aside={
          editing ? null : (
            <Button type="button" variant="link" onClick={() => setEditing(true)}>
              Change the days
            </Button>
          )
        }
      >
        The schedule
      </SectionHeading>
      {editing ? (
        <DaysForm journey={journey} onDone={() => setEditing(false)} />
      ) : (
        <>
          <ol className="grid">
            {journey.steps.map((s) => (
              <li
                key={s.step}
                className="grid grid-cols-[1.25rem_4rem_minmax(0,1fr)] items-baseline gap-x-2 border-b border-rule py-1.5 text-table last:border-b-0"
              >
                <span className="type-narrow font-semibold text-slate tabular-nums">{s.step}</span>
                <a href={`#email-${s.step}`} className="text-ink tabular-nums hover:underline">
                  {dayLabel(s.day)}
                </a>
                <span className="truncate text-slate">{s.title}</span>
              </li>
            ))}
          </ol>
          {edited ? <RestoreDays /> : null}
        </>
      )}
    </section>
  );
}

function RestoreDays() {
  const restore = useRestoreJourneyDays();
  return (
    <p className="text-table text-slate">
      These are your days, not the original ones.{" "}
      <Button
        type="button"
        variant="link"
        className="text-table"
        disabled={restore.isPending}
        onClick={() =>
          restore.mutate(undefined, {
            onSuccess: () => toast.success("Restored the original days"),
            onError: (error) => toast.error(describeError(error)),
          })
        }
      >
        Restore the original days
      </Button>
    </p>
  );
}

function DaysForm({ journey, onDone }: { journey: JourneyResponse; onDone: () => void }) {
  // Held as the day people count (Day 1 = the first email); sent as days after it.
  const [shown, setShown] = useState<Record<number, string>>(() =>
    Object.fromEntries(journey.steps.map((s) => [s.step, String(s.day + 1)])),
  );
  const save = useSaveJourneyDays();

  const days = Object.fromEntries(
    Object.entries(shown).map(([step, value]) => [Number(step), Number(value) - 1]),
  );
  const problems = dayProblems(days, journey.max_day);
  const unchanged = journey.steps.every((s) => days[s.step] === s.day);

  function onSave() {
    save.mutate(
      journey.steps.filter((s) => s.step > 1).map((s) => ({ step: s.step, day: days[s.step] })),
      {
        onSuccess: () => {
          toast.success("Saved the days");
          onDone();
        },
      },
    );
  }

  return (
    <form
      className="grid gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (problems.length === 0 && !unchanged) onSave();
      }}
    >
      <ol className="grid">
        {journey.steps.map((s) => (
          <li
            key={s.step}
            className="grid grid-cols-[1.25rem_5.5rem_minmax(0,1fr)] items-center gap-x-2 border-b border-rule py-1.5 text-table last:border-b-0"
          >
            <span className="type-narrow font-semibold text-slate tabular-nums">{s.step}</span>
            {s.step === 1 ? (
              <span className="text-ink">Day 1</span>
            ) : (
              <label className="flex items-center gap-1.5 text-ink">
                Day
                <Input
                  type="number"
                  inputMode="numeric"
                  min={2}
                  max={journey.max_day + 1}
                  value={shown[s.step]}
                  onChange={(e) => setShown((prev) => ({ ...prev, [s.step]: e.target.value }))}
                  aria-label={`Day for email ${s.step}, ${s.title}`}
                  className="h-8 w-14 px-2 tabular-nums"
                />
              </label>
            )}
            <span className="truncate text-slate">{s.title}</span>
          </li>
        ))}
      </ol>
      <div aria-live="polite" className="text-table">
        {problems.length > 0 ? (
          <ul className="grid gap-1 text-redline">
            {problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        ) : save.isError ? (
          <p className="text-redline">{describeError(save.error)}</p>
        ) : (
          <p className="text-slate">Every lead&apos;s drafts move to the new days. Nurture keeps half the pace.</p>
        )}
      </div>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" size="sm" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" size="sm" disabled={problems.length > 0 || unchanged || save.isPending}>
          {save.isPending ? "Saving…" : "Save the days"}
        </Button>
      </div>
    </form>
  );
}
