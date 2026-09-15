import type { Metadata } from "next";

import { HomeScreen } from "@/components/home/home-screen";

export const metadata: Metadata = { title: "Home" };

// Server component shell; the numbers are live and fetched on the client
// from the engine (or fixtures), so the screen itself is a client component.
export default function HomePage() {
  return <HomeScreen />;
}
