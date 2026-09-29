import { cn } from "@/lib/utils";

/** A key cap. Keys are named, never iconified. */
function Kbd({ className, ...props }: React.ComponentProps<"kbd">) {
  return (
    <kbd
      data-slot="kbd"
      className={cn(
        "inline-flex h-5 min-w-5 items-center justify-center rounded-[4px] border border-b-2 border-rule bg-sheet px-1 font-sans text-meta leading-none font-medium text-slate tabular-nums select-none",
        className,
      )}
      {...props}
    />
  );
}

export { Kbd };
