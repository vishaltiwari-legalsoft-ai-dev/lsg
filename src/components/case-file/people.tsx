import { SectionHeading } from "@/components/layout/panel";
import { EmailStatusBadge } from "@/components/record/status-badge";
import { Unknown } from "@/components/record/unknown";
import type { ContactSummary, LeadDetail } from "@/lib/api/types";
import { ROLE_LABEL } from "@/lib/labels";

function Person({ contact }: { contact: ContactSummary }) {
  return (
    <div className="grid gap-1.5">
      <div>
        <p className="text-body font-medium text-ink">{contact.full_name}</p>
        <p className="text-table text-slate">{contact.title ?? ROLE_LABEL[contact.role]}</p>
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
      <p className="text-meta text-slate">From {contact.source_label}</p>
    </div>
  );
}

/**
 * Owner and office manager, because the spec captures both — and says which
 * is missing. Anyone else found (an associate attorney, say) is listed after.
 */
export function PeopleSection({ lead }: { lead: LeadDetail }) {
  const owner = lead.contacts.find((c) => c.role === "owner") ?? null;
  const admin = lead.contacts.find((c) => c.role === "admin") ?? null;
  const others = lead.contacts.filter((c) => c !== owner && c !== admin);

  return (
    <section aria-labelledby="people-heading" className="grid gap-4">
      <SectionHeading id="people-heading">People</SectionHeading>
      <dl className="grid gap-x-8 gap-y-5 sm:grid-cols-2">
        <div className="grid content-start gap-2">
          <dt className="text-meta text-slate">Owner</dt>
          <dd>{owner ? <Person contact={owner} /> : <Unknown>No owner found yet</Unknown>}</dd>
        </div>
        <div className="grid content-start gap-2">
          <dt className="text-meta text-slate">Office manager</dt>
          <dd>{admin ? <Person contact={admin} /> : <Unknown>No office manager found yet</Unknown>}</dd>
        </div>
      </dl>
      {others.length > 0 ? (
        <div className="grid gap-3 border-t border-rule pt-4">
          <p className="text-meta text-slate">
            {others.length === 1 ? "Also found, not a decision-maker" : "Also found, not decision-makers"}
          </p>
          <div className="grid gap-5 sm:grid-cols-2">
            {others.map((contact) => (
              <Person key={contact.id} contact={contact} />
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
