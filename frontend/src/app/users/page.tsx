import type { Metadata } from "next";

import { UsersScreen } from "@/components/users/users-screen";

export const metadata: Metadata = { title: "Users" };

// Admin only (D-067): the engine refuses everyone else, and the screen says so.
export default function UsersPage() {
  return <UsersScreen />;
}
