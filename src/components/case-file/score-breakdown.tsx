import { Field, SectionHeading } from "@/components/layout/panel";
import { Unknown } from "@/components/record/unknown";
import type { LeadDetail } from "@/lib/api/types";
import { formatDecimal } from "@/lib/format";
import { CONTEST_LABEL, SCORE_LABEL } from "@/lib/labels";

const SEEDED_NOTE = "Scores use seeded weights until outcomes are recorded.";

/**
 * Each fit term and each signal's weight × decay. Labelled seeded, because
 * the weights are guesses until outcomes are recorded.
 */
export function ScoreBreakdown({ lead }: { lead: LeadDetail }) {
  const { score } = lead;
  const fitTotal = score.fit_terms.reduce((sum, t) => sum + t.points, 0);

  return (
    <section aria-labelledby="score-heading" className="grid gap-4">
      <SectionHeading id="score-heading">Why this firm, in numbers</SectionHeading>
      <p className="text-table text-slate">
        Fit is how well the firm matches (0–50). Urgency is how strong and fresh its signals are
        (0–50). Competition is how many others are likely chasing the same signal.{" "}
        {score.note || SEEDED_NOTE}
      </p>

      <dl className="grid grid-cols-3 gap-4">
        <Field label={SCORE_LABEL.fit}>
          {lead.fit === null ? <Unknown>Not scored</Unknown> : <span className="tabular-nums">{lead.fit}</span>}
        </Field>
        <Field label={SCORE_LABEL.intent}>
          {lead.intent === null ? <Unknown>Not scored</Unknown> : <span className="tabular-nums">{lead.intent}</span>}
        </Field>
        <Field label={SCORE_LABEL.contest}>
          {lead.contest === null ? <Unknown>Not scored</Unknown> : CONTEST_LABEL[lead.contest]}
        </Field>
      </dl>

      {score.fit_terms.length > 0 ? (
        <table className="w-full text-table">
          <caption className="pb-1.5 text-left text-meta text-slate">Fit terms</caption>
          <tbody className="divide-y divide-rule border-y border-rule">
            {score.fit_terms.map((term) => (
              <tr key={term.label}>
                <td className="py-1.5 pr-4 text-ink">{term.label}</td>
                <td className="py-1.5 text-right text-ink tabular-nums">{term.points}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row" className="pt-1.5 pr-4 text-left font-normal text-slate">
                Total
              </th>
              <td className="pt-1.5 text-right font-medium text-ink tabular-nums">{fitTotal}</td>
            </tr>
          </tfoot>
        </table>
      ) : null}

      <table className="w-full text-table">
        <caption className="pb-1.5 text-left text-meta text-slate">Urgency terms</caption>
        {score.intent_terms.length > 0 ? (
          <>
            <thead>
              <tr className="text-meta text-slate">
                <th scope="col" className="pb-1 text-left font-normal">Signal</th>
                <th scope="col" className="pb-1 pl-3 text-right font-normal">Weight</th>
                <th scope="col" className="pb-1 pl-3 text-right font-normal">Decay</th>
                <th scope="col" className="pb-1 pl-3 text-right font-normal">Points</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-rule border-y border-rule">
              {score.intent_terms.map((term) => (
                <tr key={term.label}>
                  <td className="py-1.5 pr-3 text-ink">{term.label}</td>
                  <td className="py-1.5 pl-3 text-right text-ink tabular-nums">{formatDecimal(term.weight)}</td>
                  <td className="py-1.5 pl-3 text-right text-ink tabular-nums">{formatDecimal(term.decay)}</td>
                  <td className="py-1.5 pl-3 text-right text-ink tabular-nums">{term.points}</td>
                </tr>
              ))}
            </tbody>
          </>
        ) : (
          <tbody>
            <tr>
              <td className="py-1.5 text-slate italic">No live signal, so urgency carries no terms.</td>
            </tr>
          </tbody>
        )}
      </table>
    </section>
  );
}
