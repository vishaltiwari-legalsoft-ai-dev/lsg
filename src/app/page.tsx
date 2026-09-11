import type { Metadata } from "next";

import { TodayScreen } from "@/components/today/today-screen";

export const metadata: Metadata = { title: "Today" };

// Server component shell; Today's data is live and fetched on the client
// from the engine (or fixtures), so the screen itself is a client component.
export default function TodayPage() {
  return <TodayScreen />;
}
