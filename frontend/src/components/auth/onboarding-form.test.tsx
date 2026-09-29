import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import authJson from "@/fixtures/auth.json";
import { ApiError } from "@/lib/api/errors";
import type { OnboardingField } from "@/lib/api/types";
import { missingAnswers, OnboardingForm } from "./onboarding-form";

const FIELDS = authJson.onboarding_fields as OnboardingField[];

// Radix Select reads pointer capture and scrolls the list; jsdom has neither.
Element.prototype.hasPointerCapture ??= () => false;
Element.prototype.releasePointerCapture ??= () => {};
Element.prototype.scrollIntoView ??= () => {};

describe("OnboardingForm", () => {
  it("names each blank required field before asking the engine", async () => {
    const onSubmit = vi.fn();
    render(<OnboardingForm fields={FIELDS} name="Priya Nair" onSubmit={onSubmit} isPending={false} error={null} />);
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.queryByText("Your name is required.")).toBeNull();
    expect(screen.getByText("Your role at Legal Soft is required.")).toBeInTheDocument();
    expect(screen.getByText("Team is required.")).toBeInTheDocument();
    expect(screen.getByText("What will you use the engine for? is required.")).toBeInTheDocument();
    expect(screen.queryByText("Phone is required.")).toBeNull();
    expect(screen.getByLabelText("Your role at Legal Soft")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("Your role at Legal Soft")).toHaveFocus();
  });

  it("posts the trimmed answers, the optional one blank, once every required field is filled", async () => {
    const onSubmit = vi.fn();
    render(<OnboardingForm fields={FIELDS} name="Priya Nair" onSubmit={onSubmit} isPending={false} error={null} />);
    await userEvent.type(screen.getByLabelText("Your role at Legal Soft"), "  SDR ");
    await userEvent.click(screen.getByRole("combobox", { name: "Team" }));
    await userEvent.click(await screen.findByRole("option", { name: "Sales" }));
    await userEvent.type(screen.getByLabelText("What will you use the engine for?"), "Work the queue.");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(onSubmit).toHaveBeenCalledWith({
      full_name: "Priya Nair",
      title: "SDR",
      team: "Sales",
      purpose: "Work the queue.",
      phone: "",
    });
  });

  it("shows the engine's own refusal as a sentence", () => {
    render(
      <OnboardingForm
        fields={FIELDS}
        name={null}
        onSubmit={vi.fn()}
        isPending={false}
        error={new ApiError(422, "validation_error", "Team: choose one of the options.", null)}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Team: choose one of the options.");
  });

  it("missingAnswers follows the engine's rule: required and blank", () => {
    expect(missingAnswers(FIELDS, { full_name: "  ", title: "SDR", team: "Sales", purpose: "x" })).toEqual({
      full_name: "Your name is required.",
    });
    expect(missingAnswers(FIELDS, { full_name: "P", title: "SDR", team: "Sales", purpose: "x" })).toEqual({});
  });
});
