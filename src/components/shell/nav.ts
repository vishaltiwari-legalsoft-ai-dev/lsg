/** Only screens that exist. Nothing links to an unbuilt screen. */
export const NAV_ITEMS = [
  { href: "/", label: "Home", hint: "What the engine does, and where things stand" },
  { href: "/leads", label: "Work queue", hint: "Every lead, by what it needs next" },
  { href: "/firms", label: "Firms", hint: "Every firm, with everything read about it" },
  { href: "/imports", label: "Lists", hint: "Upload a sheet, check how it was read, load it" },
  { href: "/review/handcheck", label: "Accuracy check", hint: "The engine's reading of 50 firms, checked by hand" },
] as const;

export function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}
