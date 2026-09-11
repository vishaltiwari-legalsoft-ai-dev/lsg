import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ContactSummary } from "@/lib/api/types";
import { AlertStateBadge, EmailStatusBadge, emailBadgeState } from "./status-badge";

function contact(status: ContactSummary["email_status"], display: string | null): ContactSummary {
  return {
    id: "c1",
    full_name: "Dana Whitfield",
    title: "Managing Partner",
    role: "owner",
    source_label: "Firm website",
    email: status ? "dana@harbor.example" : null,
    email_status: status,
    email_status_display: display,
    phone: null,
  };
}

describe("StatusBadge", () => {
  it("maps every email status to one of four states, never silently verified", () => {
    expect(emailBadgeState("valid")).toBe("verified");
    expect(emailBadgeState("unverified")).toBe("unverified");
    expect(emailBadgeState("catch_all")).toBe("failure");
    expect(emailBadgeState("risky")).toBe("failure");
    expect(emailBadgeState("invalid")).toBe("failure");
    expect(emailBadgeState(null)).toBe("no_data");
  });

  it("renders four visually distinct treatments, each carrying its word", () => {
    const cases = [
      contact("valid", "Verified"),
      contact("unverified", "Unverified — vendor says verified"),
      contact("catch_all", "Catch-all — failure"),
      contact(null, null),
    ];
    const { container } = render(
      <div>
        {cases.map((c, i) => (
          <EmailStatusBadge key={i} contact={c} />
        ))}
      </div>,
    );

    const badges = [...container.querySelectorAll<HTMLElement>("[data-state]")];
    expect(badges.map((b) => b.dataset.state)).toEqual(["verified", "unverified", "failure", "no_data"]);
    expect(badges.map((b) => b.textContent)).toEqual([
      "Verified",
      "Unverified — vendor says verified",
      "Catch-all — failure",
      "No data",
    ]);
    // Distinct classes, not just distinct words.
    expect(new Set(badges.map((b) => b.className)).size).toBe(4);
    // No data is the dashed outline, and the only one without a marker.
    const noData = badges[3];
    expect(noData.className).toContain("border-dashed");
    expect(noData.querySelector("[aria-hidden]")).toBeNull();
    for (const b of badges.slice(0, 3)) expect(b.className).not.toContain("border-dashed");
  });

  it("shows the backend's words for the vendor-says-verified case", () => {
    render(<EmailStatusBadge contact={contact("unverified", "Unverified — vendor says verified")} />);
    expect(screen.getByText("Unverified — vendor says verified")).toBeInTheDocument();
  });

  it("gives alerts three distinct treatments: ok, firing, no data", () => {
    const { container } = render(
      <div>
        <AlertStateBadge state="ok" />
        <AlertStateBadge state="firing" />
        <AlertStateBadge state="no_data" />
      </div>,
    );
    const badges = [...container.querySelectorAll<HTMLElement>("[data-state]")];
    expect(badges.map((b) => b.textContent)).toEqual(["OK", "Firing", "No data"]);
    expect(new Set(badges.map((b) => b.className)).size).toBe(3);
  });
});
