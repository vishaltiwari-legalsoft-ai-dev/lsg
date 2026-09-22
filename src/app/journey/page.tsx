import type { Metadata } from "next";
import { Suspense } from "react";

import { JourneyScreen } from "@/components/journey/journey-screen";
import { TitleBar } from "@/components/shell/title-bar";

export const metadata: Metadata = { title: "Email journey" };

// The example firm and track are read from the URL (useSearchParams), so the
// screen renders under a Suspense boundary.
export default function JourneyPage() {
  return (
    <Suspense fallback={<TitleBar title="Email journey" />}>
      <JourneyScreen />
    </Suspense>
  );
}
