"use client";

import { useEffect, useRef } from "react";

/** Typing into a field, or working inside a dialog, never triggers a shortcut. */
export function isShortcutBlocked(event: KeyboardEvent): boolean {
  if (event.defaultPrevented || event.isComposing) return true;
  const target = event.target;
  if (!(target instanceof Element)) return false;
  if (target.closest('[role="dialog"], [role="alertdialog"], [role="listbox"], [role="menu"]')) {
    return true;
  }
  if (target instanceof HTMLElement && target.isContentEditable) return true;
  const tag = target.tagName;
  if (tag === "TEXTAREA" || tag === "SELECT") return true;
  if (tag === "INPUT") {
    const type = (target as HTMLInputElement).type;
    return !["checkbox", "radio", "button", "submit", "reset"].includes(type);
  }
  return false;
}

/**
 * A window-level keydown listener that always sees the latest handler
 * without re-subscribing on every render.
 */
export function useKeydown(handler: (event: KeyboardEvent) => void, enabled = true) {
  const latest = useRef(handler);
  useEffect(() => {
    latest.current = handler;
  });
  useEffect(() => {
    if (!enabled) return;
    const listener = (event: KeyboardEvent) => latest.current(event);
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, [enabled]);
}
