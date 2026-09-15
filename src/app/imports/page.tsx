import type { Metadata } from "next";
import { Suspense } from "react";

import { ImportsScreen } from "@/components/imports/imports-screen";
import { TitleBar } from "@/components/shell/title-bar";

export const metadata: Metadata = { title: "Lists" };

export default function ImportsPage() {
  return (
    <Suspense fallback={<TitleBar title="Imports" meta="Sheets" />}>
      <ImportsScreen />
    </Suspense>
  );
}
