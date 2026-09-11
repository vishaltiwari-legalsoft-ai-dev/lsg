import { cva, type VariantProps } from "class-variance-authority";
import { Slot } from "radix-ui";
import * as React from "react";

import { cn } from "@/lib/utils";

/*
 * Cobalt means act, so only the primary variant is cobalt. Controls carry the
 * 6px radius. No press-down translate: movement only answers a person, and
 * the colour change already does.
 */
const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-1.5 rounded-control font-medium whitespace-nowrap select-none transition-colors duration-100 disabled:pointer-events-none disabled:opacity-45 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
  {
    variants: {
      variant: {
        primary: "bg-cobalt text-white hover:bg-cobalt-deep",
        secondary:
          "border border-rule bg-sheet text-ink hover:border-rule-strong hover:bg-paper aria-pressed:border-cobalt aria-pressed:bg-cobalt-wash",
        ghost: "text-slate hover:bg-paper hover:text-ink aria-expanded:bg-paper aria-expanded:text-ink",
        danger: "border border-redline/35 bg-sheet text-redline hover:border-redline/60 hover:bg-redline-wash",
        "danger-solid": "bg-redline text-white hover:bg-redline/90",
        link: "text-cobalt underline-offset-3 hover:underline",
      },
      size: {
        sm: "h-7 px-2.5 text-table",
        md: "h-8 px-3 text-body",
        lg: "h-10 px-4 text-body",
        icon: "size-8",
        "icon-sm": "size-7",
      },
    },
    compoundVariants: [{ variant: "link", className: "h-auto px-0" }],
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: React.ComponentProps<"button"> & VariantProps<typeof buttonVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : "button";
  return (
    <Comp
      data-slot="button"
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  );
}

export { Button, buttonVariants };
