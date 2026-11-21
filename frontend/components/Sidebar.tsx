"use client";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { BookOpen, FileDown, FileWarning, GanttChartSquare, LayoutDashboard, Mail, Smartphone, Timer } from "lucide-react";
import { useApi } from "@/lib/api";
import { LangToggle, useT } from "@/lib/i18n";

const NAV = [
  { href: "", label: "Dashboard", icon: LayoutDashboard },
  { href: "/erfassungen", label: "Erfassungen", icon: Timer },
  { href: "/bauzeitenplan", label: "Bauzeitenplan", icon: GanttChartSquare },
  { href: "/schreiben", label: "Schreiben", icon: FileWarning },
  { href: "/postfach", label: "Postfach", icon: Mail },
  { href: "/vertrag", label: "Vertrag / LV", icon: BookOpen },
  { href: "/export", label: "Export", icon: FileDown },
];

export default function Sidebar() {
  const { pid } = useParams<{ pid: string }>();
  const path = usePathname();
  const { t } = useT();
  const { data: projects } = useApi<any[]>("/api/projects", 15_000);
  return (
    <nav className="flex h-full w-64 shrink-0 flex-col border-r border-slate-200 bg-white px-4 py-4 text-base max-md:w-14 max-md:px-1.5">
      <div className="mb-4 flex items-center gap-2 px-1 text-lg font-semibold">
        <img src="/icon.svg" alt="" className="h-7 w-7" /> <span className="max-md:hidden">SiteVox</span>
        <span className="ml-auto max-md:hidden"><LangToggle /></span>
      </div>
      <div className="mb-1 px-1 text-xs uppercase tracking-wide text-slate-500 max-md:hidden">{t("Projekte")}</div>
      <ul className="space-y-0.5">
        {(projects || []).sort((a, b) => b.badge - a.badge || a.name.localeCompare(b.name)).map((p) => (
          <li key={p.id}>
            <Link href={`/p/${p.id}`} title={`${p.title} · ${t("{n} fristgebundene Schreiben offen", { n: p.badge })}`}
              className={`flex items-center justify-between rounded-md px-3 py-2 ${p.id === pid ? "bg-slate-100 font-medium" : "text-slate-600 hover:bg-slate-50"}`}>
              <span className="truncate max-md:text-2xs">{p.name}</span>
              {p.badge > 0 && <span className="ml-1 rounded-full bg-bad px-1.5 text-2xs font-semibold text-white">{p.badge}</span>}
            </Link>
          </li>
        ))}
      </ul>
      <div className="my-3 border-t border-slate-200" />
      <ul className="space-y-0.5">
        {NAV.map(({ href, label, icon: Icon }) => {
          const full = `/p/${pid}${href}`;
          const active = href === "" ? path === full : path.startsWith(full);
          return (
            <li key={href}>
              <Link href={full} title={t(label)}
                className={`flex items-center gap-3 rounded-md px-3 py-2 ${active ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-50"}`}>
                <Icon className="h-5 w-5 shrink-0" /> <span className="max-md:hidden">{t(label)}</span>
              </Link>
            </li>
          );
        })}
      </ul>
      <Link href={`/m/${pid}`} className="mt-auto flex items-center gap-3 rounded-md px-3 py-2 text-sm text-slate-600 hover:bg-slate-50" title={t("Baustellen-Modus")}>
        <Smartphone className="h-5 w-5" /> <span className="max-md:hidden">{t("Baustellen-Modus")}</span>
      </Link>
    </nav>
  );
}
