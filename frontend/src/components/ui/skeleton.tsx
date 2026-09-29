import { cn } from "@/lib/utils";

/**
 * A placeholder in the shape of what is coming. Deliberately still: the
 * highlighter is the only motion nobody asked for.
 */
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      aria-hidden="true"
      className={cn("rounded-control bg-rule/65", className)}
      {...props}
    />
  );
}

export { Skeleton };
