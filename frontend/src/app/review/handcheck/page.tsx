import type { Metadata } from "next";
import { Suspense } from "react";

import { HandcheckScreen } from "@/components/handcheck/handcheck-screen";
import { TitleBar } from "@/components/shell/title-bar";

export const metadata: Metadata = { title: "Accuracy check" };

export default function HandcheckPage() {
  return (
    <Suspense fallback={<TitleBar title="Accuracy check" />}>
      <HandcheckScreen />
    </Suspense>
  );
}
