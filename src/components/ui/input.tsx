import * as React from "react";

import { cn } from "@/lib/utils";

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "h-8 w-full min-w-0 rounded-control border border-rule bg-sheet px-2.5 text-body text-ink transition-colors outline-offset-0 placeholder:text-slate hover:border-rule-strong disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-redline",
        className,
      )}
      {...props}
    />
  );
}

export { Input };
