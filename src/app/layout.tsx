import type { Metadata } from "next";
import { Libre_Caslon_Text, Rubik } from "next/font/google";

import { Rail } from "@/components/shell/rail";
import { Providers } from "./providers";
import "./globals.css";

// Rubik: Legal Soft's brand-kit portal face, for the whole interface.
const rubik = Rubik({
  subsets: ["latin"],
  variable: "--font-rubik",
  display: "swap",
});

// Libre Caslon Text: the record only — evidence quotations and quoted email copy.
const caslon = Libre_Caslon_Text({
  subsets: ["latin"],
  weight: ["400"],
  style: ["normal", "italic"],
  variable: "--font-caslon",
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "Lead Gen Engine", template: "%s — Lead Gen Engine" },
  description: "Legal Soft's lead intelligence: the proof, the people and the first email.",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${rubik.variable} ${caslon.variable}`}>
      <body>
        <a
          href="#main"
          className="sr-only z-50 rounded-control bg-cobalt px-3 py-2 text-white focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
        >
          Skip to content
        </a>
        <Providers>
          <Rail />
          <div className="flex min-h-screen flex-col md:pl-(--rail-width)">
            <main id="main" className="flex min-w-0 flex-1 flex-col">
              {children}
            </main>
          </div>
        </Providers>
      </body>
    </html>
  );
}
