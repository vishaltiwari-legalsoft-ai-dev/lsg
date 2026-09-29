import type { Metadata } from "next";

import { FirmScreen } from "@/components/firms/firm-screen";

export const metadata: Metadata = { title: "Firm record" };

export default async function FirmPage(props: PageProps<"/firms/[id]">) {
  const { id } = await props.params;
  return <FirmScreen id={decodeURIComponent(id)} />;
}
