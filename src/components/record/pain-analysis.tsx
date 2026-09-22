import { SectionHeading } from "@/components/layout/panel";
import type { PainAnalysis as Analysis } from "@/lib/api/types";
import { formatDate } from "@/lib/format";

/**
 * What the AI read on this firm and what it says hurts (D-058). Every pain
 * carries the line that proves it and the part of the record that line came
 * from -- a pain the engine could not prove was thrown away before this was
 * ever written. The summary is the model's own words and nothing checks
 * them, so it is set apart from the proven lines rather than mixed in.
 */
export function PainAnalysis({ pain, id = "pain-heading" }: { pain: Analysis; id?: string }) {
  return (
    <section aria-labelledby={id} className="grid gap-4">
      <SectionHeading id={id} aside={`Read ${formatDate(pain.at)}`}>
        What hurts
      </SectionHeading>

      <p className="max-w-[68ch] text-body text-slate">{pain.summary}</p>

      {pain.pains.length > 0 ? (
        <ol className="grid gap-5 border-t border-rule pt-4">
          {pain.pains.map((p, i) => (
            <li key={`${p.kind}-${i}`} className="grid gap-1.5">
              <p className="text-section font-semibold text-ink">{p.headline}</p>
              <p className="quotation border-l-2 border-rule pl-4 text-quote text-ink">
                {p.quote}
              </p>
              <p className="text-meta text-slate">From {p.source}</p>
              <p className="text-body text-slate">{p.why_it_matters}</p>
            </li>
          ))}
        </ol>
      ) : null}

      <p className="text-meta text-slate">
        Read from {pain.read.join(", ")}.
        {pain.pains.length === 0
          ? " Nothing in it proved a need, so nothing is claimed."
          : " Each line above is quoted from the record, not written by the AI."}
      </p>
    </section>
  );
}
