/**
 * The rail follows the three steps of the brief (plan-v3): raw leads come in,
 * they are enriched, they are handed over. Only screens that exist are
 * listed -- nothing links to an unbuilt screen; a step's future screens
 * (batches, handovers) join its group when they are built.
 */
export interface NavItem {
  href: string;
  label: string;
  hint: string;
}

export interface NavStep {
  step: 1 | 2 | 3;
  label: string;
  items: NavItem[];
}

export const NAV_HOME: NavItem = {
  href: "/",
  label: "Home",
  hint: "What the engine does, how to use it, and where things stand",
};

export const NAV_STEPS: NavStep[] = [
  {
    step: 1,
    label: "Raw leads",
    items: [
      { href: "/imports", label: "Sheets", hint: "Upload a sheet, check how it was read, load it" },
    ],
  },
  {
    step: 2,
    label: "Enrichment",
    items: [
      { href: "/leads", label: "Work queue", hint: "Every lead, by what it needs next" },
      { href: "/firms", label: "Firms", hint: "Every firm, with everything read about it" },
      {
        href: "/review/handcheck",
        label: "Accuracy check",
        hint: "The engine's reading of 50 firms, checked by hand",
      },
    ],
  },
  {
    step: 3,
    label: "Handover",
    items: [
      {
        href: "/qualified",
        label: "Actual leads",
        hint: "Enriched leads and what each still lacks; the ready ones go to a vendor",
      },
      {
        href: "/journey",
        label: "Email journey",
        hint: "What each lead is sent, day by day; change the words and the days",
      },
    ],
  },
];

/**
 * The admin's own group, under the three steps (D-067). Only an admin sees
 * it: nothing links to a screen the person cannot open.
 */
export const NAV_ACCOUNT: { label: string; items: NavItem[] } = {
  label: "Account",
  items: [{ href: "/users", label: "Users", hint: "Who has signed in, and what each may do" }],
};

/** Every screen everyone has, in rail order -- for the command palette. */
export const NAV_ITEMS: NavItem[] = [NAV_HOME, ...NAV_STEPS.flatMap((s) => s.items)];

/** Whether the signed-in person gets the Account group: an admin with access. */
export function showsAccount(status: { standing: string; user: { access: string } | null } | undefined): boolean {
  return status?.standing === "active" && status.user?.access === "admin";
}

/** Every screen this person can open, in rail order. */
export function navItemsFor(status: Parameters<typeof showsAccount>[0]): NavItem[] {
  return showsAccount(status) ? [...NAV_ITEMS, ...NAV_ACCOUNT.items] : NAV_ITEMS;
}

export function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}
