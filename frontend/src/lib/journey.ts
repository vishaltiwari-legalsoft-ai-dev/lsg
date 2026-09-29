/**
 * The email journey's rules as the screens use them (D-057). The engine owns
 * them (lge/journey/catalogue.py); these repeat its checks word for word so
 * the editor can say what is wrong while a person types, and the fixture
 * server can stand in for the engine. Every save is checked again there.
 */
import type { JourneyTemplate } from "@/lib/api/types";

/** The engine counts days after the first email; people count from Day 1. */
export function dayLabel(daysAfterFirst: number): string {
  return `Day ${daysAfterFirst + 1}`;
}

const TOKEN_RE = /\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g;

/** Every `{name}` in `text`, first occurrence order, no repeats. */
export function tokensIn(text: string): string[] {
  return [...new Set([...text.matchAll(TOKEN_RE)].map((m) => m[1]))];
}

export function bannedIn(text: string, banned: string[]): string[] {
  const lowered = text.toLowerCase();
  return banned.filter((phrase) => lowered.includes(phrase.toLowerCase()));
}

const MAX_SUBJECT = 150;
const MAX_BODY = 3000;

type Checked = Pick<JourneyTemplate, "kind" | "fill_ins" | "keeps">;

/** Why an edit cannot be saved; empty when it can. */
export function copyProblems(
  template: Checked,
  subject: string | null,
  body: string,
  banned: string[],
): string[] {
  const problems: string[] = [];
  const subj = subject ?? "";
  const noun = template.kind === "email" ? "email" : "paragraph";

  if (template.kind === "email") {
    if (!subj.trim()) problems.push("Add a subject line.");
    else if (/[\r\n]/.test(subj)) problems.push("Keep the subject on one line.");
    else if (subj.length > MAX_SUBJECT) problems.push(`Keep the subject under ${MAX_SUBJECT} characters.`);
  } else if (subj.trim()) {
    problems.push("A paragraph has no subject line.");
  }

  if (!body.trim()) problems.push(`The ${noun} can't be empty.`);
  else if (body.length > MAX_BODY) problems.push(`Keep the ${noun} under 3,000 characters.`);

  const text = `${subj}\n${body}`;
  const hits = bannedIn(text, banned);
  if (hits.length > 0) {
    problems.push(
      `It uses words these emails never use: ${hits.map((p) => `“${p}”`).join(", ")}. ` +
        "They read as replacing someone's staff, and the email dies in that person's inbox.",
    );
  }

  const allowed = new Set(template.fill_ins);
  const unknown = tokensIn(text).filter((t) => !allowed.has(t) && t !== template.keeps);
  if (unknown.length > 0) {
    const names = unknown.map((t) => `{${t}}`).join(", ");
    const canUse = template.fill_ins.map((t) => `{${t}}`).join(", ");
    problems.push(`${names} can't be filled in here. This ${noun} can use ${canUse}.`);
  }

  const bare = text.replace(TOKEN_RE, "");
  if (bare.includes("{") || bare.includes("}")) {
    problems.push("A { or } that is not part of a fill-in would be sent as it is.");
  }

  if (template.keeps) {
    const slot = `{${template.keeps}}`;
    if (body.split(slot).length - 1 !== 1 || subj.includes(slot)) {
      problems.push(`Keep ${slot} in the body exactly once: the tier's paragraph goes there.`);
    }
  }
  return problems;
}

/** Why a schedule cannot be saved; empty when it can. `days` holds every email's days after email 1. */
export function dayProblems(days: Record<number, number>, maxDay: number): string[] {
  const steps = Object.keys(days).map(Number).sort((a, b) => a - b);
  const problems: string[] = [];
  for (const step of steps) {
    if (step === 1) {
      if (days[step] !== 0) problems.push("Email 1 always goes on Day 1.");
    } else if (!Number.isInteger(days[step]) || days[step] < 1 || days[step] > maxDay) {
      problems.push(`Email ${step} must go between Day 2 and Day ${maxDay + 1}.`);
    }
  }
  if (problems.length > 0) return problems;
  for (const step of steps.slice(1)) {
    const previous = days[step - 1];
    if (previous !== undefined && days[step] <= previous) {
      problems.push(`Email ${step} must come after email ${step - 1}, which goes on Day ${previous + 1}.`);
    }
  }
  return problems;
}

/** Words as a reader counts them; a fill-in is one word. */
export function wordCount(text: string): number {
  return text.split(/\s+/).filter(Boolean).length;
}

/** The journey's subject lines are lowercase; a capital outside a fill-in is worth a second look. */
export function subjectHasCapitals(subject: string): boolean {
  return /[A-Z]/.test(subject.replace(TOKEN_RE, ""));
}
