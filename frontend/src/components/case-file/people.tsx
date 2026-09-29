"use client";

import { ArrowUpRightIcon } from "lucide-react";
import { useState } from "react";

import { SectionHeading } from "@/components/layout/panel";
import { EmailStatusBadge } from "@/components/record/status-badge";
import { Unknown } from "@/components/record/unknown";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useContactEdits } from "@/lib/api/hooks";
import type { ContactCreate, ContactSummary, LeadDetail, Role } from "@/lib/api/types";
import { ROLE_LABEL } from "@/lib/labels";

const ROLES: Role[] = ["owner", "admin", "attorney", "unknown"];

type Edits = ReturnType<typeof useContactEdits>;

function PersonDialog({
  contact,
  open,
  onClose,
  onSubmit,
}: {
  contact: ContactSummary | null;
  open: boolean;
  onClose: () => void;
  onSubmit: (values: ContactCreate) => void;
}) {
  const [values, setValues] = useState<ContactCreate>({
    full_name: contact?.full_name ?? "",
    title: contact?.title ?? "",
    role: contact?.role ?? "unknown",
    email: contact?.email ?? "",
    phone: contact?.phone ?? "",
    linkedin_url: contact?.linkedin_url ?? "",
  });
  const set = (key: keyof ContactCreate) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setValues((v) => ({ ...v, [key]: e.target.value }));
  const field = "h-8 text-table";

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? undefined : onClose())}>
      <DialogContent>
        <form
          className="grid gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            onSubmit(values);
            onClose();
          }}
        >
          <DialogHeader>
            <DialogTitle>{contact ? `Correct ${contact.full_name}` : "Add a person"}</DialogTitle>
            <DialogDescription>
              {contact
                ? "What you enter replaces what the engine read. An address you add is kept as unverified until it is checked."
                : "Someone the engine missed. The record shows they were added by hand."}
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid gap-1.5 sm:col-span-2">
              <Label htmlFor="person-name">Name</Label>
              <Input id="person-name" value={values.full_name} onChange={set("full_name")} required className={field} />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="person-title">Title</Label>
              <Input id="person-title" value={values.title ?? ""} onChange={set("title")} placeholder="Office Manager" className={field} />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="person-role">Role</Label>
              <select
                id="person-role"
                value={values.role ?? "unknown"}
                onChange={set("role")}
                className="h-8 rounded-md border border-rule bg-sheet px-2 text-table text-ink"
              >
                {ROLES.map((role) => (
                  <option key={role} value={role}>
                    {ROLE_LABEL[role]}
                  </option>
                ))}
              </select>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="person-email">Email</Label>
              <Input id="person-email" type="email" value={values.email ?? ""} onChange={set("email")} className={field} />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="person-phone">Direct phone</Label>
              <Input id="person-phone" value={values.phone ?? ""} onChange={set("phone")} className={field} />
            </div>
            <div className="grid gap-1.5 sm:col-span-2">
              <Label htmlFor="person-linkedin">LinkedIn profile</Label>
              <Input id="person-linkedin" value={values.linkedin_url ?? ""} onChange={set("linkedin_url")} placeholder="https://www.linkedin.com/in/…" className={field} />
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" variant="primary">
              {contact ? "Save" : "Add person"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Person({
  contact,
  primary,
  edits,
  canChoose,
}: {
  contact: ContactSummary;
  primary: boolean;
  edits: Edits;
  canChoose: boolean;
}) {
  const [editing, setEditing] = useState(false);
  return (
    <div className="grid gap-1.5">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-body font-medium text-ink">
            {contact.full_name}
            {primary ? <span className="ml-2 text-meta font-normal text-cobalt">Primary</span> : null}
          </p>
          <p className="text-table text-slate">{contact.title ?? ROLE_LABEL[contact.role]}</p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {contact.email ? (
          <a href={`mailto:${contact.email}`} className="text-table text-cobalt hover:underline">
            {contact.email}
          </a>
        ) : (
          <Unknown className="text-table">No email found</Unknown>
        )}
        <EmailStatusBadge contact={contact} />
      </div>
      {contact.phone ? <p className="text-table text-ink tabular-nums">{contact.phone}</p> : null}
      {contact.linkedin_url ? (
        <span className="grid gap-0.5">
          <a
            href={contact.linkedin_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-0.5 text-meta text-cobalt hover:underline"
          >
            LinkedIn profile
            <ArrowUpRightIcon className="size-3" aria-hidden="true" />
          </a>
          {contact.linkedin_headline ? (
            <span className="text-meta text-slate">{contact.linkedin_headline}</span>
          ) : null}
        </span>
      ) : null}
      <p className="text-meta text-slate">From {contact.source_label}</p>
      <div className="flex flex-wrap gap-1">
        {canChoose && !primary ? (
          <Button size="sm" variant="ghost" onClick={() => edits.setPrimary.mutate(contact.id)}>
            Make primary
          </Button>
        ) : null}
        <Button size="sm" variant="ghost" onClick={() => setEditing(true)}>
          Correct
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="text-redline"
          onClick={() => {
            if (window.confirm(`Strike out ${contact.full_name}? They stay on the record as removed.`)) {
              edits.remove.mutate({ contactId: contact.id, reason: "wrong person" });
            }
          }}
        >
          Not a person / wrong
        </Button>
      </div>
      {editing ? (
        <PersonDialog
          contact={contact}
          open={editing}
          onClose={() => setEditing(false)}
          onSubmit={(values) =>
            edits.patch.mutate({
              contactId: contact.id,
              body: {
                full_name: values.full_name,
                title: values.title ?? "",
                role: values.role ?? null,
                email: values.email || null,
                phone: values.phone ?? "",
                linkedin_url: values.linkedin_url ?? "",
              },
            })
          }
        />
      ) : null}
    </div>
  );
}

/**
 * Owner and office manager, because the spec captures both — and says which
 * is missing. Anyone else found is listed after. Each person can be made the
 * primary contact, corrected, or struck out; a person the engine missed can
 * be added by hand.
 */
export function PeopleSection({ lead }: { lead: LeadDetail }) {
  const edits = useContactEdits(lead.firm.id, lead.id);
  const [adding, setAdding] = useState(false);
  const owner = lead.contacts.find((c) => c.role === "owner") ?? null;
  const admin = lead.contacts.find((c) => c.role === "admin") ?? null;
  const others = lead.contacts.filter((c) => c !== owner && c !== admin);
  const primaryId = lead.contact?.id ?? null;
  const person = (contact: ContactSummary) => (
    <Person contact={contact} primary={contact.id === primaryId} edits={edits} canChoose />
  );

  return (
    <section aria-labelledby="people-heading" className="grid gap-4">
      <SectionHeading
        id="people-heading"
        aside={
          <Button size="sm" variant="secondary" onClick={() => setAdding(true)}>
            Add a person
          </Button>
        }
      >
        People
      </SectionHeading>
      <dl className="grid gap-x-8 gap-y-5 sm:grid-cols-2">
        <div className="grid content-start gap-2">
          <dt className="text-meta text-slate">Owner</dt>
          <dd>{owner ? person(owner) : <Unknown>No owner found yet</Unknown>}</dd>
        </div>
        <div className="grid content-start gap-2">
          <dt className="text-meta text-slate">Office manager</dt>
          <dd>{admin ? person(admin) : <Unknown>No office manager found yet</Unknown>}</dd>
        </div>
      </dl>
      {others.length > 0 ? (
        <div className="grid gap-3 border-t border-rule pt-4">
          <p className="text-meta text-slate">
            {others.length === 1 ? "Also found, not a decision-maker" : "Also found, not decision-makers"}
          </p>
          <div className="grid gap-5 sm:grid-cols-2">
            {others.map((contact) => (
              <div key={contact.id}>{person(contact)}</div>
            ))}
          </div>
        </div>
      ) : null}
      {adding ? (
        <PersonDialog
          contact={null}
          open={adding}
          onClose={() => setAdding(false)}
          onSubmit={(values) =>
            edits.add.mutate({
              full_name: values.full_name,
              title: values.title || null,
              role: values.role ?? null,
              email: values.email || null,
              phone: values.phone || null,
              linkedin_url: values.linkedin_url || null,
            })
          }
        />
      ) : null}
    </section>
  );
}
