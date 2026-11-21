"use client";
import { useT } from "@/lib/i18n";
import Link from "next/link";
import { useParams } from "next/navigation";
import { AlertTriangle, Mail } from "lucide-react";
import { dLong, useApi } from "@/lib/api";
import { ConfidencePill, Elapsed, SphereChip, StatusChip } from "@/components/ui";

const FLOW = ["Entwurf", "Geprüft", "Versendet"];

export default function Letters() {
  const { pid } = useParams<{ pid: string }>();
  const { data } = useApi<any[]>(`/api/projects/${pid}/letters`, 10_000);
  const { data: events } = useApi<any[]>(`/api/projects/${pid}/events`, 10_000);
  const open = (events || []).filter((e) => e.status !== "dismissed" && !e.letter);
  const { t } = useT();
  return (
    <div className="mx-auto max-w-4xl p-4">
      <h1 className="mb-1 text-lg font-semibold">{t("Schreiben")}</h1>
      <p className="mb-4 text-xs text-slate-600">{t("Status: {s}. „Versendet“ setzt nur die Bauleitung nach eigenem Versand.", { s: FLOW.map((f) => t(f)).join(" → ") })}</p>
      <div className="grid gap-2">
        {(data || []).map((l) => (
          <Link key={l.letter_id} href={`/p/${pid}/schreiben/${l.letter_id}`} className="card flex min-w-0 items-center gap-3 p-3 hover:bg-slate-50">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 font-medium">{t(l.kind_label)} <span className="text-xs font-normal text-slate-500">{l.letter_id}</span></div>
              <div className="truncate text-xs text-slate-600">{l.betreff}</div>
              {l.recipient_email_status !== "rejected" && (l.recipient_email
                ? <div className="flex items-center gap-1 truncate text-xs text-slate-700"><Mail className="h-3.5 w-3.5 shrink-0" /> {t("An:")} {l.recipient_email}</div>
                : l.status === "Entwurf" && <div className="flex items-center gap-1 text-xs font-medium text-bad-text"><AlertTriangle className="h-3.5 w-3.5 shrink-0" /> {t("E-Mail-Adresse des AG fehlt – bitte prüfen und eintragen")}</div>)}
              <div className="text-2xs text-slate-500">{t("erstellt {d}", { d: dLong(l.created_at) })}{l.deadline && l.status !== "Versendet" && <> · <Elapsed from={l.deadline.detected_at} level={l.deadline.level} label={l.deadline.label} /></>}</div>
            </div>
            {l.open_issues > 0 && <span className="pill bg-bad-soft text-bad-text">{t("{n} nicht belegt", { n: l.open_issues })}</span>}
            <StatusChip status={l.status} />
          </Link>
        ))}
        {data && !data.length && <p className="text-sm text-slate-600">{t("Noch keine Schreiben. Entwürfe entstehen aus „Handlungsbedarf“ im Dashboard.")}</p>}
      </div>

      {open.length > 0 && (
        <>
          <h2 className="mb-1 mt-8 font-semibold">{t("Ereignisse ohne Schreiben an den AG")}</h2>
          <p className="mb-3 text-xs text-slate-600">{t("Interne Ereignisse (AN-Risiko) und Ereignisse, für die noch kein Entwurf erstellt wurde.")}</p>
          <div className="grid gap-2">
            {open.map((e) => (
              <Link key={e.event_id} href={`/p/${pid}/schreiben/ereignis/${e.event_id}`} className="card flex items-center gap-3 p-3 hover:bg-slate-50">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2 font-medium">
                    {t(e.label)}{e.affected_activities?.length ? ` – ${e.affected_activities.map((a: string) => t(a)).join(", ")}` : ""}
                    <span className="text-xs font-normal text-slate-500">{e.event_id}</span>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-2xs text-slate-600">
                    <SphereChip sphere={e.sphere} confirmed={e.sphere_confirmed} />
                    <span>{t(e.recommended_document.label)}{e.recommended_document.requires_letter ? "" : ` · ${t("kein Schreiben an AG")}`}</span>
                    <span>{dLong(e.start)} {e.start.slice(11, 16)}</span>
                  </div>
                </div>
                <ConfidencePill value={e.confidence?.overall} />
              </Link>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
