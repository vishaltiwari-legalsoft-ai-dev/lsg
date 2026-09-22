import * as React from "react";

import { cn } from "@/lib/utils";

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "h-9 w-full min-w-0 rounded-control border border-rule-strong/70 bg-sheet px-3 text-body text-ink transition-colors outline-offset-0 placeholder:text-slate hover:border-rule-strong disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-redline",
        className,
      )}
      {...props}
    />
  );
}

export { Input };
