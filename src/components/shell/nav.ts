/** Only screens that exist. Nothing links to an unbuilt screen. */
export const NAV_ITEMS = [
  { href: "/", label: "Today", hint: "The strongest proof, and what needs a human" },
  { href: "/leads", label: "Leads", hint: "The ranked list, by band" },
  { href: "/firms", label: "Firms", hint: "Every firm, with its record" },
  { href: "/review/handcheck", label: "Hand-check", hint: "Gate G2: check 50 firms by hand" },
  { href: "/imports", label: "Imports", hint: "Upload a sheet, check how it was read, load it" },
] as const;

export function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}
