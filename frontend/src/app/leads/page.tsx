import type { Metadata } from "next";
import { Suspense } from "react";

import { LeadsScreen } from "@/components/leads/leads-screen";
import { TitleBar } from "@/components/shell/title-bar";

export const metadata: Metadata = { title: "Work queue" };

// The screen reads its band, filters and selection from the URL
// (useSearchParams), so it renders under a Suspense boundary.
export default function LeadsPage() {
  return (
    <Suspense fallback={<TitleBar title="Work queue" />}>
      <LeadsScreen />
    </Suspense>
  );
}
