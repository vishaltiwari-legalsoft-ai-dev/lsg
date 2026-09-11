import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(() => {
  cleanup();
});

/**
 * jsdom has no matchMedia. Tests opt into reduced motion with
 * `setReducedMotion(true)`; the default is "no preference".
 */
let reduced = false;
export function setReducedMotion(value: boolean) {
  reduced = value;
}

Object.defineProperty(window, "matchMedia", {
  writable: true,
  configurable: true,
  value: vi.fn((query: string) => ({
    matches: query.includes("prefers-reduced-motion") ? reduced : false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});
