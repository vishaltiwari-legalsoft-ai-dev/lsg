import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AttributeValue, UNKNOWN_TEXT, Unknown, ValueOrUnknown } from "./unknown";

describe("unknown values", () => {
  it("writes the unknown in words, slate italic", () => {
    render(<Unknown />);
    const el = screen.getByText("Unknown — not guessed");
    expect(el).toHaveClass("italic", "text-slate");
  });

  it("renders an unknown attribute from the backend's display", () => {
    render(<AttributeValue display="Unknown — not guessed" state="unknown" />);
    expect(screen.getByText(UNKNOWN_TEXT)).toHaveAttribute("data-unknown");
  });

  it("never renders a blank, even if the display comes back empty", () => {
    const { container } = render(<AttributeValue display="   " state="unknown" />);
    expect(container.textContent).toBe(UNKNOWN_TEXT);
  });

  it.each([null, undefined, "", "  "])("treats %j as unknown rather than a blank", (value) => {
    const { container } = render(<ValueOrUnknown value={value} />);
    expect(container.textContent).toBe(UNKNOWN_TEXT);
    expect(container.querySelector("[data-unknown]")).not.toBeNull();
  });

  it("recognises the backend's own unknown wording in a plain display field", () => {
    const { container } = render(<ValueOrUnknown value="Unknown — not guessed" />);
    expect(container.querySelector("[data-unknown]")).not.toBeNull();
  });

  it("keeps a real zero as a value, not an unknown", () => {
    const { container } = render(<ValueOrUnknown value={0} />);
    expect(container.textContent).toBe("0");
    expect(container.querySelector("[data-unknown]")).toBeNull();
  });

  it("uses a specific phrase when one is given", () => {
    render(<ValueOrUnknown value={null} unknown="No direct line" />);
    expect(screen.getByText("No direct line")).toHaveAttribute("data-unknown");
  });

  it("renders a resolved value plainly", () => {
    render(<AttributeValue display="Contingency" state="resolved" />);
    const el = screen.getByText("Contingency");
    expect(el).not.toHaveAttribute("data-unknown");
    expect(el).not.toHaveClass("italic");
  });
});
