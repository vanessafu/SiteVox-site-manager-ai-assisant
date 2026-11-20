import type { Metadata, Viewport } from "next";
import "./globals.css";
import SWRegister from "@/components/SWRegister";
import { LangProvider } from "@/lib/i18n";

export const metadata: Metadata = {
  title: "SiteVox – Bauleiter-Assistent",
  description: "Erfassung, Soll-Ist, Anzeigen-Entwürfe mit Belegen. Keine Rechtsberatung.",
  manifest: "/manifest.webmanifest",
  icons: { icon: "/icon.svg" },
};
export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#0f172a" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="de">
      <body>
        <LangProvider>{children}</LangProvider>
        <SWRegister />
      </body>
    </html>
  );
}
