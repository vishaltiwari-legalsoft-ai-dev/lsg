import type { Metadata } from "next";
import { Suspense } from "react";

import { QualifiedScreen } from "@/components/qualified/qualified-screen";
import { TitleBar } from "@/components/shell/title-bar";

export const metadata: Metadata = { title: "Actual leads" };

// The screen reads its tab and search from the URL (useSearchParams), so it
// renders under a Suspense boundary.
export default function QualifiedPage() {
  return (
    <Suspense fallback={<TitleBar title="Actual leads" />}>
      <QualifiedScreen />
    </Suspense>
  );
}
