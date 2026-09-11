"use client";

import { Toaster as Sonner, type ToasterProps } from "sonner";

/*
 * Toasts are a floating layer: sheet, rule, the one shadow, panel radius.
 * Unstyled so none of sonner's default look leaks through. The state is
 * carried by a short rule on the left edge plus the words — never colour
 * alone, and no icon parade.
 */
function Toaster(props: ToasterProps) {
  return (
    <Sonner
      // Bottom-left, clear of the rail: the case file's outcome bar owns the
      // bottom-right, and a toast must never cover the next decision.
      position="bottom-left"
      offset={{ bottom: 24, left: "calc(var(--rail-width) + 24px)" }}
      mobileOffset={{ bottom: 16, left: 16 }}
      gap={10}
      visibleToasts={4}
      toastOptions={{
        unstyled: true,
        classNames: {
          toast:
            "group relative flex w-[min(380px,calc(100vw-2rem))] items-start gap-3 overflow-hidden rounded-panel border border-rule bg-sheet py-3.5 pr-4 pl-5 text-body text-ink shadow-float before:absolute before:inset-y-3 before:left-2 before:w-[3px] before:bg-rule-strong data-[type=error]:before:bg-redline data-[type=success]:before:bg-ledger",
          icon: "hidden",
          title: "font-normal leading-snug",
          description: "mt-0.5 text-table text-slate",
          actionButton:
            "ml-auto shrink-0 rounded-control px-2 py-1 text-table font-medium text-cobalt hover:bg-cobalt-wash",
        },
      }}
      {...props}
    />
  );
}

export { Toaster };
