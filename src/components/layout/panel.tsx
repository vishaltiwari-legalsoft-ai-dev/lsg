import { cn } from "@/lib/utils";

/** A document surface: sheet, one rule, the 10px panel radius, no shadow. */
export function Panel({ className, ...props }: React.ComponentProps<"section">) {
  return (
    <section className={cn("rounded-panel border border-rule bg-sheet", className)} {...props} />
  );
}

/** A section title in Archivo 600, sentence case, with an optional aside. */
export function SectionHeading({
  id,
  children,
  aside,
  level = 2,
  className,
}: {
  id?: string;
  children: React.ReactNode;
  aside?: React.ReactNode;
  level?: 2 | 3;
  className?: string;
}) {
  const Tag = level === 2 ? "h2" : "h3";
  return (
    <div className={cn("flex items-baseline justify-between gap-4", className)}>
      <Tag id={id} className="text-section font-semibold text-ink">
        {children}
      </Tag>
      {aside ? <div className="text-table text-slate">{aside}</div> : null}
    </div>
  );
}

/** A labelled value in a record: slate label above, ink value below. */
export function Field({
  label,
  children,
  className,
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("grid min-w-0 gap-0.5", className)}>
      <dt className="text-meta text-slate">{label}</dt>
      <dd className="min-w-0 text-body text-ink">{children}</dd>
    </div>
  );
}
