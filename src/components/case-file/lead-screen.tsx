"use client";

import Link from "next/link";

import { Panel } from "@/components/layout/panel";
import { TitleBar, TitlePlaceholder } from "@/components/shell/title-bar";
import { buttonVariants } from "@/components/ui/button";
import { useLead } from "@/lib/api/hooks";
import { CaseFile } from "./case-file";

/** The case file on its own page: everything expanded, keys live anywhere. */
export function LeadScreen({ id }: { id: string }) {
  const lead = useLead(id);
  const title = lead.data?.firm.name ?? (lead.isPending ? null : "Case file");

  return (
    <>
      <TitleBar
        title={title ?? <TitlePlaceholder />}
        actions={
          <Link href={`/leads?lead=${encodeURIComponent(id)}`} className={buttonVariants({ variant: "ghost" })}>
            Back to the docket
          </Link>
        }
      />
      <div className="max-w-[60rem] px-8 pt-8 pb-16">
        <Panel>
          <CaseFile id={id} mode="page" />
        </Panel>
      </div>
    </>
  );
}
