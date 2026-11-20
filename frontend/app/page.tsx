"use client";
import Link from "next/link";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { HardHat, Monitor } from "lucide-react";
import { LangToggle, useT } from "@/lib/i18n";

// Ein PWA, zwei Ansichten: Handy → Baustellen-Modus (Erfassung), Tablet/Desktop → Container-Büro.
export default function Home() {
  const router = useRouter();
  const { t } = useT();
  useEffect(() => {
    const auto = new URLSearchParams(window.location.search).get("auto") !== "0";
    if (auto && window.matchMedia("(max-width: 640px)").matches) router.replace("/m/BV-RIEM");
  }, [router]);
  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-4 p-6">
      <div className="flex items-center justify-between"><h1 className="text-2xl font-semibold">SiteVox</h1><LangToggle /></div>
      <p className="text-sm text-slate-600">{t("KI-Assistent für die Bauleitung – Dokumentation, Tagesberichte, Anzeigen.")}</p>
      <Link href="/p/BV-RIEM" className="card flex items-center gap-3 p-4 hover:bg-slate-50">
        <Monitor className="h-6 w-6" /> <div><div className="font-medium">{t("Container-Büro")}</div><div className="text-xs text-slate-600">{t("Dashboard, Prüfung, Export")}</div></div>
      </Link>
      <Link href="/m/BV-RIEM" className="card flex items-center gap-3 p-4 hover:bg-slate-50">
        <HardHat className="h-6 w-6" /> <div><div className="font-medium">{t("Baustelle")}</div><div className="text-xs text-slate-600">{t("Sprachmemo, Foto, Notiz")}</div></div>
      </Link>
    </main>
  );
}
