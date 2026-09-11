import type { Metadata } from "next";

import { LeadScreen } from "@/components/case-file/lead-screen";

export const metadata: Metadata = { title: "Case file" };

export default async function LeadPage(props: PageProps<"/leads/[id]">) {
  const { id } = await props.params;
  return <LeadScreen id={decodeURIComponent(id)} />;
}
