"use client";
/** Verlauf: alle Berichtstage des Projekts. Klick öffnet das komplette Dashboard dieses Tages (nicht nur das PDF). */
import Link from "next/link";
import { useParams } from "next/navigation";
import { AlertTriangle, Camera, ChevronRight, CloudRain, FileDown, History, Mic, Truck } from "lucide-react";
import { dLong, num, useApi } from "@/lib/api";
import { useT } from "@/lib/i18n";

export default function Verlauf() {
  const { pid } = useParams<{ pid: string }>();
  const { t } = useT();
  const { data: days, error } = useApi<any[]>(`/api/projects/${pid}/days`);
  if (error) return <div className="p-6 text-sm text-bad-text">{error}</div>;
  if (!days) return <div className="p-6 text-sm text-slate-500">{t("lädt …")}</div>;
  return (
    <div className="mx-auto max-w-4xl space-y-3 px-4 py-4 lg:px-6">
      <div className="section-head">
        <h1 className="flex items-center gap-2 text-lg font-semibold"><History className="h-5 w-5" /> {t("Verlauf")}</h1>
        <span className="text-xs text-slate-600">{t("Frühere Tage als komplettes Dashboard ansehen")}</span>
      </div>
      {!days.length && <p className="text-sm text-slate-600">{t("Noch keine Berichtstage vorhanden.")}</p>}
      <ul className="card divide-y divide-slate-100">
        {days.map((x) => (
          <li key={x.date} className="flex items-center gap-3 px-4 py-3 hover:bg-slate-50">
            <Link href={`/p/${pid}/verlauf/${x.date}`}
              className="flex min-w-0 flex-1 flex-wrap items-center gap-x-4 gap-y-1">
              <span className="w-44 text-base font-semibold tabular-nums">{dLong(x.date)}</span>
              {x.captures > 0 && <span className="inline-flex items-center gap-1 text-xs text-slate-600"><Mic className="h-3.5 w-3.5" />{t("{n} Erfassungen", { n: x.captures })}</span>}
              {x.photos > 0 && <span className="inline-flex items-center gap-1 text-xs text-slate-600"><Camera className="h-3.5 w-3.5" />{x.photos}</span>}
              {x.deliveries > 0 && <span className="inline-flex items-center gap-1 text-xs text-slate-600" title={x.delivery_materials?.join(", ")}><Truck className="h-3.5 w-3.5" />{t("{n} Lieferungen", { n: x.deliveries })}</span>}
              {x.deliveries_open > 0 && <span className="pill bg-warn-soft text-warn-text">{t("{n} Lieferung offen", { n: x.deliveries_open })}</span>}
              {x.events > 0 && <span className="inline-flex items-center gap-1 text-xs text-warn-text"><AlertTriangle className="h-3.5 w-3.5" />{t("{n} Ereignisse", { n: x.events })}</span>}
              {x.open_letters > 0 && <span className="pill bg-bad-soft text-bad-text">{t("{n} Schreiben offen", { n: x.open_letters })}</span>}
              {x.weather && <span className="inline-flex items-center gap-1 text-xs text-slate-600"><CloudRain className="h-3.5 w-3.5" />{t(x.weather)}{x.temp_max != null ? ` · ${num(x.temp_max)} °C` : ""}</span>}
              <ChevronRight className="ml-auto h-4 w-4 text-slate-400" />
            </Link>
            <a className="btn-xs" href={`/api/projects/${pid}/daily-report?date=${x.date}`} title={t("Bautagesbericht exportieren")}><FileDown className="h-3.5 w-3.5" /> PDF</a>
          </li>
        ))}
      </ul>
    </div>
  );
}
