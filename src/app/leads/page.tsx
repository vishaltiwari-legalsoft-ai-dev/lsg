import type { Metadata } from "next";
import { Suspense } from "react";

import { LeadsScreen } from "@/components/leads/leads-screen";
import { TitleBar } from "@/components/shell/title-bar";

export const metadata: Metadata = { title: "Leads" };

// The screen reads its band, filters and selection from the URL
// (useSearchParams), so it renders under a Suspense boundary.
export default function LeadsPage() {
  return (
    <Suspense fallback={<TitleBar title="Leads" />}>
      <LeadsScreen />
    </Suspense>
  );
}
