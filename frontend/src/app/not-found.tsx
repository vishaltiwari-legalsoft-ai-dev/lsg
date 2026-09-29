import Link from "next/link";

import { TitleBar } from "@/components/shell/title-bar";
import { EmptyState } from "@/components/states/empty-state";
import { buttonVariants } from "@/components/ui/button";

export default function NotFound() {
  return (
    <>
      <TitleBar title="Not found" />
      <div className="px-8">
        <EmptyState
          title="There's no screen at this address."
          action={
            <Link href="/" className={buttonVariants({ variant: "secondary" })}>
              Go to Home
            </Link>
          }
        >
          Check the link, or search for a firm with Ctrl K.
        </EmptyState>
      </div>
    </>
  );
}
