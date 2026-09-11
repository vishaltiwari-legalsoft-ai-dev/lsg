import { cn } from "@/lib/utils";

/**
 * Empty states give direction, not mood: what is missing and what will make
 * it appear. Left-aligned, no illustration.
 */
export function EmptyState({
  title,
  children,
  action,
  className,
}: {
  title: string;
  children?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("grid max-w-[60ch] justify-items-start gap-2 py-10", className)}>
      <p className="text-section font-medium text-ink">{title}</p>
      {children ? <div className="text-body text-slate">{children}</div> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}
