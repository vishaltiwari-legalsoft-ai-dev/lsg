import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import authJson from "@/fixtures/auth.json";
import usersJson from "@/fixtures/users.json";
import { EngineUnreachableError } from "@/lib/api/errors";
import { useAuth, useOnboarding, useSignOut } from "@/lib/api/hooks";
import type { AuthStatus, AuthUser } from "@/lib/api/types";
import { AuthGate } from "./auth-gate";

vi.mock("next/navigation", () => ({ usePathname: () => "/leads" }));
vi.mock("@/lib/api/hooks", () => ({
  useAuth: vi.fn(),
  useOnboarding: vi.fn(),
  useSignOut: vi.fn(),
}));

const users = (usersJson as { items: AuthUser[] }).items;
const priya = users.find((u) => u.id === "user-fx-priya")!;
const vishal = users.find((u) => u.id === "user-fx-vishal")!;

function status(over: Partial<AuthStatus>): AuthStatus {
  return { ...(authJson as AuthStatus), configured: true, ...over };
}

type AuthResult = ReturnType<typeof useAuth>;

function answer(result: Partial<AuthResult>) {
  vi.mocked(useAuth).mockReturnValue({
    isPending: false,
    isError: false,
    data: undefined,
    error: null,
    refetch: vi.fn(),
    ...result,
  } as unknown as AuthResult);
}

function show() {
  return render(
    <AuthGate rail={<div>THE RAIL</div>}>
      <div>THE SCREEN</div>
    </AuthGate>,
  );
}

beforeEach(() => {
  vi.mocked(useSignOut).mockReturnValue({ mutate: vi.fn(), isPending: false } as unknown as ReturnType<typeof useSignOut>);
  vi.mocked(useOnboarding).mockReturnValue({ mutate: vi.fn(), isPending: false, error: null } as unknown as ReturnType<typeof useOnboarding>);
  window.history.replaceState(null, "", "/leads");
});

describe("AuthGate", () => {
  it("shows the frame with nothing on it while the engine says who is asking -- never the sign-in screen", () => {
    answer({ isPending: true });
    show();
    expect(screen.getByLabelText("Checking who is signed in")).toBeInTheDocument();
    expect(screen.queryByText("Sign in with Google")).toBeNull();
    expect(screen.queryByText("THE SCREEN")).toBeNull();
  });

  it("shows the app as before while sign-in is off", () => {
    answer({ data: status({ standing: "off", configured: false }) });
    show();
    expect(screen.getByText("THE RAIL")).toBeInTheDocument();
    expect(screen.getByText("THE SCREEN")).toBeInTheDocument();
  });

  it("shows the app to a person with access", () => {
    answer({ data: status({ standing: "active", user: vishal }) });
    show();
    expect(screen.getByText("THE RAIL")).toBeInTheDocument();
    expect(screen.getByText("THE SCREEN")).toBeInTheDocument();
  });

  it("shows the sign-in screen, without the rail, to someone signed out", () => {
    answer({ data: status({ standing: "signed_out" }) });
    show();
    expect(screen.queryByText("THE RAIL")).toBeNull();
    expect(screen.getByRole("link", { name: "Sign in with Google" })).toHaveAttribute(
      "href",
      "/api/auth/google/start?next=%2Fleads",
    );
    expect(screen.getByText("Only Google accounts at legalsoft.com can use this door.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    // The other door: a person from an email vendor's team, any Google
    // account, admitted only when the vendor list names them.
    expect(screen.getByRole("radio", { name: /I'm from Legal Soft/ })).toBeChecked();
    fireEvent.click(screen.getByRole("radio", { name: /email vendor's team/ }));
    expect(screen.getByRole("link", { name: "Sign in with Google as a vendor" })).toHaveAttribute(
      "href",
      "/api/auth/google/start?kind=vendor&next=%2Fleads",
    );
  });

  it("says in words why a sign-in came back, then drops the reason from the URL", async () => {
    window.history.replaceState(null, "", "/leads?signin=domain&lead=x");
    answer({ data: status({ standing: "signed_out" }) });
    show();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("That Google account isn't at legalsoft.com.");
    await waitFor(() => expect(window.location.search).toBe("?lead=x"));
  });

  it("shows the form, with the name Google gave, to someone who has not filled it", () => {
    answer({
      data: status({ standing: "needs_onboarding", user: { ...priya, standing: "needs_onboarding", onboarding: null } }),
    });
    show();
    expect(screen.getByRole("heading", { name: "Before you start, tell us who you are" })).toBeInTheDocument();
    expect(screen.getByLabelText("Your name")).toHaveValue("Priya Nair");
    expect(screen.getByRole("button", { name: "Continue" })).toBeInTheDocument();
    expect(screen.queryByText("THE RAIL")).toBeNull();
  });

  it("tells someone waiting that Vishal has to set their access, with a way out", () => {
    answer({ data: status({ standing: "awaiting_access", user: priya }) });
    show();
    expect(screen.getByRole("heading", { name: "You're in. Vishal has to set your access first." })).toBeInTheDocument();
    expect(screen.getByText("priya.nair@legalsoft.com")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });

  it("tells someone turned off that they are, with a way out", () => {
    answer({ data: status({ standing: "disabled", user: { ...priya, access: "disabled", standing: "disabled" } }) });
    show();
    expect(screen.getByRole("heading", { name: "Your access has been turned off." })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });

  it("reuses the error state when the engine cannot be reached", () => {
    answer({ isError: true, error: new EngineUnreachableError() });
    show();
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't reach the engine.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
