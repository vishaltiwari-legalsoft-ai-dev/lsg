"use client";

import { toast } from "sonner";

import { Button } from "@/components/ui/button";

async function writeClipboard(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  // Fallback for contexts without the async clipboard API.
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  const ok = document.execCommand("copy");
  area.remove();
  if (!ok) throw new Error("Clipboard unavailable");
}

/** "Copy first email" gives the toast "Copied first email": one name through the flow. */
export function CopyButton({
  text,
  label,
  toastText,
  variant = "secondary",
  size = "sm",
  className,
  "aria-label": ariaLabel,
}: {
  text: string;
  label: string;
  toastText: string;
  variant?: "primary" | "secondary" | "ghost";
  size?: "sm" | "md" | "lg";
  className?: string;
  "aria-label"?: string;
}) {
  return (
    <Button
      type="button"
      variant={variant}
      size={size}
      className={className}
      aria-label={ariaLabel}
      onClick={async () => {
        try {
          await writeClipboard(text);
          toast.success(toastText);
        } catch {
          toast.error("Couldn't copy to the clipboard. Select the text and copy it by hand.");
        }
      }}
    >
      {label}
    </Button>
  );
}

/** Subject and body as one pasteable email. */
export function emailText(subject: string, body: string): string {
  return `Subject: ${subject}\n\n${body}`;
}
