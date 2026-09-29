import type { Metadata } from "next";
import { Suspense } from "react";

import { FirmsScreen } from "@/components/firms/firms-screen";
import { TitleBar } from "@/components/shell/title-bar";

export const metadata: Metadata = { title: "Firms" };

export default function FirmsPage() {
  return (
    <Suspense fallback={<TitleBar title="Firms" />}>
      <FirmsScreen />
    </Suspense>
  );
}
