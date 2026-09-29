import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import drafts from "@/fixtures/drafts.json";
import type { DraftsResponse } from "@/lib/api/types";
import { DraftSequence } from "./draft-sequence";

const all = drafts as unknown as Record<string, DraftsResponse>;

describe("DraftSequence", () => {
  it("counts days from Day 1 and links to the lead's journey", () => {
    render(
      <DraftSequence drafts={all["lead-fx-harbor"]} isPending={false} isError={false} expand="first" leadId="lead-fx-harbor" />,
    );
    expect(screen.getByText("Day 1")).toBeInTheDocument();
    expect(screen.getByText("Day 29")).toBeInTheDocument();
    expect(screen.queryByText("Day 0")).toBeNull();
    expect(screen.getByText("9 of 9 emails, over 29 days")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy email 1" })).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "See this journey day by day, and change the wording" }),
    ).toHaveAttribute("href", "/journey?lead=lead-fx-harbor");
  });

  it("gives a skipped email no day and counts only the written ones", () => {
    render(<DraftSequence drafts={all["lead-atlinjurylawgroup"]} isPending={false} isError={false} expand="first" />);
    expect(screen.getByText("7 of 9 emails, over 29 days")).toBeInTheDocument();
    expect(screen.getAllByText(/^Day \d+$/)).toHaveLength(7);
    expect(screen.queryByRole("link")).toBeNull(); // no lead id, no link
  });
});
