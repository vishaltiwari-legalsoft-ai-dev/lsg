"use client";

import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { describeError } from "@/lib/api/errors";
import type { OnboardingField } from "@/lib/api/types";
import { cn } from "@/lib/utils";

export type Answers = Record<string, string>;

/** The first answers: the name Google gave, and nothing else filled in. */
export function initialAnswers(fields: OnboardingField[], name: string | null): Answers {
  const answers: Answers = {};
  for (const field of fields) answers[field.name] = field.name === "full_name" ? (name ?? "") : "";
  return answers;
}

/** The engine's own rule, applied before asking it: a required field cannot be blank. */
export function missingAnswers(fields: OnboardingField[], answers: Answers): Record<string, string> {
  const problems: Record<string, string> = {};
  for (const field of fields) {
    if (field.required && !(answers[field.name] ?? "").trim()) {
      problems[field.name] = `${field.label} is required.`;
    }
  }
  return problems;
}

const fieldClass =
  "w-full min-w-0 rounded-control border border-rule-strong/70 bg-sheet px-3 py-2 text-body text-ink transition-colors placeholder:text-slate hover:border-rule-strong aria-invalid:border-redline";

function FieldControl({
  field,
  id,
  value,
  invalid,
  describedBy,
  onChange,
}: {
  field: OnboardingField;
  id: string;
  value: string;
  invalid: boolean;
  describedBy: string | undefined;
  onChange: (value: string) => void;
}) {
  if (field.kind === "long_text") {
    return (
      <textarea
        id={id}
        name={field.name}
        value={value}
        rows={3}
        maxLength={2000}
        aria-required={field.required}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
        onChange={(e) => onChange(e.target.value)}
        className={fieldClass}
      />
    );
  }
  if (field.kind === "choice") {
    return (
      <Select value={value || undefined} onValueChange={onChange} name={field.name}>
        <SelectTrigger
          id={id}
          aria-required={field.required}
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy}
          className={cn("w-full text-body", invalid && "border-redline")}
        >
          <SelectValue placeholder="Choose one" />
        </SelectTrigger>
        <SelectContent>
          {(field.options ?? []).map((option) => (
            <SelectItem key={option} value={option}>
              {option}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    );
  }
  return (
    <Input
      id={id}
      name={field.name}
      type={field.name === "phone" ? "tel" : "text"}
      autoComplete={field.name === "full_name" ? "name" : field.name === "phone" ? "tel" : undefined}
      value={value}
      aria-required={field.required}
      aria-invalid={invalid || undefined}
      aria-describedby={describedBy}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

/**
 * The form a new person fills once, rendered from the engine's own fields.
 * It is the whole of what the admin will see about them, so the labels and
 * hints are the engine's words. Blank required fields are named before the
 * engine is asked; the engine's refusal (422) is shown as its own sentence.
 */
export function OnboardingForm({
  fields,
  name,
  onSubmit,
  isPending,
  error,
}: {
  fields: OnboardingField[];
  /** The name Google gave, prefilled. */
  name: string | null;
  onSubmit: (answers: Answers) => void;
  isPending: boolean;
  error: unknown;
}) {
  const base = useId();
  const [answers, setAnswers] = useState<Answers>(() => initialAnswers(fields, name));
  const [problems, setProblems] = useState<Record<string, string>>({});

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const missing = missingAnswers(fields, answers);
    setProblems(missing);
    if (Object.keys(missing).length > 0) {
      const first = fields.find((f) => missing[f.name]);
      if (first) document.getElementById(`${base}-${first.name}`)?.focus();
      return;
    }
    const trimmed: Answers = {};
    for (const field of fields) trimmed[field.name] = (answers[field.name] ?? "").trim();
    onSubmit(trimmed);
  }

  return (
    <form onSubmit={submit} noValidate className="grid gap-5">
      {fields.map((field) => {
        const id = `${base}-${field.name}`;
        const problem = problems[field.name];
        const hintId = field.hint ? `${id}-hint` : undefined;
        const problemId = problem ? `${id}-problem` : undefined;
        const describedBy = [problemId, hintId].filter(Boolean).join(" ") || undefined;
        return (
          <div key={field.name} className="grid gap-1.5">
            <Label htmlFor={id}>
              {field.label}
              {field.required ? null : <span className="ml-1.5 font-normal text-slate">Optional</span>}
            </Label>
            <FieldControl
              field={field}
              id={id}
              value={answers[field.name] ?? ""}
              invalid={Boolean(problem)}
              describedBy={describedBy}
              onChange={(value) => {
                setAnswers((a) => ({ ...a, [field.name]: value }));
                if (problem) setProblems((p) => ({ ...p, [field.name]: "" }));
              }}
            />
            {problem ? (
              <p id={problemId} className="text-table text-redline">
                {problem}
              </p>
            ) : null}
            {field.hint ? (
              <p id={hintId} className="text-table text-slate">
                {field.hint}
              </p>
            ) : null}
          </div>
        );
      })}
      {error ? (
        <p role="alert" className="border-l-2 border-redline py-1 pl-3 text-body text-ink">
          {describeError(error)}
        </p>
      ) : null}
      <div className="mt-1">
        <Button type="submit" variant="primary" size="lg" disabled={isPending}>
          {isPending ? "Sending…" : "Continue"}
        </Button>
      </div>
    </form>
  );
}
