"use client";

import { useState } from "react";

import { SectionHeading } from "@/components/layout/panel";
import { Button } from "@/components/ui/button";
import { useAddNote } from "@/lib/api/hooks";
import type { LeadDetail } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";

/** The lead's notes, newest first, and a line to add one. */
export function NotesSection({ lead }: { lead: LeadDetail }) {
  const addNote = useAddNote(lead.id);
  const [text, setText] = useState("");

  return (
    <section aria-labelledby="notes-heading" className="grid gap-4">
      <SectionHeading id="notes-heading" aside={lead.notes.length ? `${lead.notes.length}` : undefined}>
        Notes
      </SectionHeading>
      <form
        className="grid gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          const trimmed = text.trim();
          if (!trimmed) return;
          addNote.mutate(trimmed, { onSuccess: () => setText("") });
        }}
      >
        <textarea
          aria-label="New note"
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={2}
          maxLength={2000}
          placeholder="What happened, what to do next"
          className="w-full rounded-md border border-rule bg-sheet px-3 py-2 text-body text-ink outline-none focus-visible:border-cobalt"
        />
        <div>
          <Button type="submit" size="sm" variant="secondary" disabled={!text.trim() || addNote.isPending}>
            {addNote.isPending ? "Saving…" : "Add note"}
          </Button>
        </div>
      </form>
      {lead.notes.length === 0 ? (
        <p className="text-body text-slate">No notes yet. Decisions you make from here are noted automatically.</p>
      ) : (
        <ol className="grid gap-2" aria-label="Notes, newest first">
          {lead.notes.map((note) => (
            <li key={note.id} className="grid grid-cols-[8.5rem_minmax(0,1fr)] gap-3 text-body">
              <span className="text-table text-slate tabular-nums">
                {formatDateTime(note.at)}
                <span className="block">{note.actor}</span>
              </span>
              <span className="whitespace-pre-wrap text-ink">{note.text}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
