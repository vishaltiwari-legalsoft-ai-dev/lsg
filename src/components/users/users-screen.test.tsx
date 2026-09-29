import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import userEventsJson from "@/fixtures/user-events.json";
import usersJson from "@/fixtures/users.json";
import { ApiError } from "@/lib/api/errors";
import { useSetUserAccess, useUser, useUsers } from "@/lib/api/hooks";
import type { UserDetail, UserEvent, UsersResponse } from "@/lib/api/types";
import { eventWords } from "./user-words";
import { UsersScreen, waitingFirst } from "./users-screen";

vi.mock("@/lib/api/hooks", () => ({
  useUsers: vi.fn(),
  useUser: vi.fn(),
  useSetUserAccess: vi.fn(),
}));

const fixture = usersJson as UsersResponse;
const events = userEventsJson as Record<string, UserEvent[]>;

function listed(result: Partial<ReturnType<typeof useUsers>>) {
  vi.mocked(useUsers).mockReturnValue({
    isPending: false, isError: false, data: undefined, error: null, refetch: vi.fn(), ...result,
  } as unknown as ReturnType<typeof useUsers>);
}

beforeEach(() => {
  vi.mocked(useSetUserAccess).mockReturnValue({
    mutate: vi.fn(), isPending: false, variables: undefined,
  } as unknown as ReturnType<typeof useSetUserAccess>);
  vi.mocked(useUser).mockImplementation((id) => {
    const user = fixture.items.find((u) => u.id === id)!;
    const detail: UserDetail = { user, events: events[id ?? ""] ?? [] };
    return { isPending: false, isError: false, data: detail, error: null, refetch: vi.fn() } as unknown as ReturnType<typeof useUser>;
  });
});

describe("UsersScreen", () => {
  it("lists the ones waiting first, marked, whatever order they arrive in", () => {
    listed({ data: { ...fixture, items: [...fixture.items].reverse() } });
    render(<UsersScreen />);
    const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
    expect(within(rows[0]).getByText("Priya Nair")).toBeInTheDocument();
    expect(within(rows[0]).getByText("Waiting for you")).toBeInTheDocument();
    expect(screen.getAllByText("Waiting for you")).toHaveLength(1);
    expect(screen.getByText("5 people have signed in, 1 waiting for you")).toBeInTheDocument();
  });

  it("gives every person a control but the admin by settings, who is named as such", () => {
    listed({ data: fixture });
    render(<UsersScreen />);
    expect(screen.getAllByRole("combobox")).toHaveLength(4);
    const vishal = screen.getByText("Vishal Tiwari").closest("tr")!;
    expect(within(vishal).queryByRole("combobox")).toBeNull();
    expect(within(vishal).getByText("Admin by the engine's settings")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Access for Priya Nair" })).toHaveTextContent("Choose a level");
    expect(screen.getByRole("combobox", { name: "Access for Marcus Hale" })).toHaveTextContent("Operator");
  });

  it("opens a row to the full answers and the history in plain words", async () => {
    listed({ data: fixture });
    render(<UsersScreen />);
    await userEvent.click(screen.getByRole("button", { name: "Open Marcus Hale" }));
    expect(screen.getByText("Access set to Operator by vishal.tiwari@legalsoft.com")).toBeInTheDocument();
    expect(screen.getByText("Filled the form")).toBeInTheDocument();
    expect(screen.getByText("Signed up")).toBeInTheDocument();
    expect(screen.getByText("Account executive", { selector: "dd" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close Marcus Hale" })).toHaveAttribute("aria-expanded", "true");
  });

  it("says when nobody else has signed in", () => {
    listed({ data: { ...fixture, items: [], waiting: 0 } });
    render(<UsersScreen />);
    expect(screen.getByText("Nobody else has signed in yet.")).toBeInTheDocument();
  });

  it("says who may see it, and when sign-in is off, in words", () => {
    listed({ isError: true, error: new ApiError(403, "admin_only", "Only an admin can see or change who has access.", null) });
    const { unmount } = render(<UsersScreen />);
    expect(screen.getByText("Only an admin can see this.")).toBeInTheDocument();
    unmount();
    listed({ isError: true, error: new ApiError(409, "sign_in_off", "Sign-in is not configured on this engine.", null) });
    render(<UsersScreen />);
    expect(screen.getByText("Sign-in is not switched on for this engine yet.")).toBeInTheDocument();
    expect(screen.getByText("GOOGLE_OAUTH_CLIENT_ID GOOGLE_OAUTH_CLIENT_SECRET")).toBeInTheDocument();
  });

  it("shows a skeleton while the list loads", () => {
    listed({ isPending: true });
    render(<UsersScreen />);
    expect(screen.getByLabelText("Loading who has signed in")).toBeInTheDocument();
  });
});

describe("user words", () => {
  it("keeps the engine's order within each group", () => {
    const ids = waitingFirst([...fixture.items].reverse()).map((u) => u.id);
    expect(ids).toEqual(["user-fx-priya", "user-fx-tom", "user-fx-elena", "user-fx-marcus", "user-fx-vishal"]);
  });

  it("turns every event kind into words, never a code", () => {
    const at = "2026-09-28T08:00:00Z";
    expect(eventWords({ kind: "signed_up", detail: { access: "admin", admin_by_settings: true }, actor: "v", at }, fixture.levels))
      .toBe("Signed up, an admin by the engine's settings");
    expect(eventWords({ kind: "access_set", detail: { from: "pending", to: "admin", by: "settings" }, actor: "v", at }, fixture.levels))
      .toBe("Access set to Admin by the engine's settings");
    expect(eventWords({ kind: "password_reset", detail: null, actor: "v", at }, fixture.levels)).toBe("Password reset");
  });
});
