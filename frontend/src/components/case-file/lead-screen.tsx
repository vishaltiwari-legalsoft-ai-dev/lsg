"use client";

import { ArrowLeftIcon } from "lucide-react";
import Link from "next/link";

import { TierMark } from "@/components/record/tier-mark";
import { TitleBar, TitlePlaceholder } from "@/components/shell/title-bar";
import { buttonVariants } from "@/components/ui/button";
import { useLead } from "@/lib/api/hooks";
import { CaseFile } from "./case-file";

/**
 * The lead on its own page: the firm's name as the caption of its record,
 * and the case file opened into its two columns. Keys are live anywhere.
 */
export function LeadScreen({ id }: { id: string }) {
  const lead = useLead(id);
  const title = lead.data?.firm.name ?? (lead.isPending ? null : "Lead");

  return (
    <>
      <TitleBar
        caption={Boolean(lead.data)}
        title={title ?? <TitlePlaceholder />}
        // The stage and the next step lead the working side; the header keeps to the tier.
        meta={lead.data ? <TierMark firm={lead.data.firm} /> : undefined}
        actions={
          <Link
            href={`/leads?stage=${lead.data?.stage ?? "needs_review"}&lead=${encodeURIComponent(id)}`}
            className={buttonVariants({ variant: "ghost" })}
          >
            <ArrowLeftIcon aria-hidden="true" />
            Work queue
          </Link>
        }
      />
      <CaseFile id={id} mode="page" />
    </>
  );
}
