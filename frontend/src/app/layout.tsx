import type { Metadata } from "next";
import { Archivo, Libre_Caslon_Display, Libre_Caslon_Text } from "next/font/google";

import { AuthGate } from "@/components/auth/auth-gate";
import { Rail } from "@/components/shell/rail";
import { Providers } from "./providers";
import "./globals.css";

// Archivo: the interface. Its width axis gives titles and figures the
// narrow, heavy voice of the Legal Soft wordmark (`type-narrow`).
const archivo = Archivo({
  subsets: ["latin"],
  axes: ["wdth"],
  variable: "--font-archivo",
  display: "swap",
});

// Libre Caslon Text: the record -- the sentences the engine read, the emails it drafts.
const caslon = Libre_Caslon_Text({
  subsets: ["latin"],
  weight: ["400", "700"],
  style: ["normal", "italic"],
  variable: "--font-caslon",
  display: "swap",
});

// Libre Caslon Display: a firm's name, set large as the caption of its record.
const caslonDisplay = Libre_Caslon_Display({
  subsets: ["latin"],
  weight: "400",
  variable: "--font-caslon-display",
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "Lead Gen Engine", template: "%s — Lead Gen Engine" },
  description: "Legal Soft's lead intelligence: the proof, the people and the first email.",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${archivo.variable} ${caslon.variable} ${caslonDisplay.variable}`}>
      <body>
        <a
          href="#main"
          className="sr-only z-50 rounded-control bg-cobalt px-3 py-2 text-white focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
        >
          Skip to content
        </a>
        <Providers>
          {/* The gate (D-067) shows the app -- rail and sheet -- to a person
              with access, and one sheet saying where they stand to anyone
              else. The rail is built here so it stays a server component. */}
          <AuthGate rail={<Rail />}>{children}</AuthGate>
        </Providers>
      </body>
    </html>
  );
}
