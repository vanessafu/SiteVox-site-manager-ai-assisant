"use client";
import { useT } from "@/lib/i18n";
import Link from "next/link";
import { useParams } from "next/navigation";
import { FileDown, Mail } from "lucide-react";
import { useApi } from "@/lib/api";
import { StatusChip } from "@/components/ui";

export default function ExportPage() {
  const { pid } = useParams<{ pid: string }>();
  const { data: dash } = useApi<any>(`/api/projects/${pid}/dashboard`);
  const { data: letters } = useApi<any[]>(`/api/projects/${pid}/letters`);
  const { t } = useT();
  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4">
      <h1 className="text-lg font-semibold">{t("Export")}</h1>
      <div className="card p-4">
        <div className="mb-2 font-medium">{t("Bautagesbericht")}</div>
        <p className="mb-2 text-xs text-slate-600">{t("Entwurf aus Erfassungen, Soll-Ist, Wetter (DWD), Ereignissen und Fotos (Gesichter automatisch verpixelt, mit Zeitstempel/GPS).")}</p>
        {dash && <a className="btn" href={`/api/projects/${pid}/daily-report?date=${dash.date}`}><FileDown className="h-[18px] w-[18px]" /> {t("Bautagesbericht {d} (DOCX)", { d: dash.date })}</a>}
      </div>
      <div className="card p-4">
        <div className="mb-2 font-medium">{t("Schreiben")}</div>
        <p className="mb-2 text-xs text-slate-600">{t("Export erst nach Freigabe. Outlook-Entwurf als .eml (X-Unsent) – der Versand erfolgt durch Sie.")}</p>
        <ul className="space-y-2">{(letters || []).map((l) => (
          <li key={l.letter_id} className="flex flex-wrap items-center gap-2 text-sm">
            <Link className="font-medium hover:underline" href={`/p/${pid}/schreiben/${l.letter_id}`}>{t(l.kind_label)} {l.letter_id}</Link> <StatusChip status={l.status} />
            {l.status !== "Entwurf" && l.status !== "Verworfen" ? (
              <span className="ml-auto flex gap-1"><a className="btn-xs" href={`/api/letters/${l.letter_id}/export/docx`}>DOCX</a><a className="btn-xs" href={`/api/letters/${l.letter_id}/export/pdf`}>PDF</a><a className="btn-xs" href={`/api/letters/${l.letter_id}/export/eml`}><Mail className="h-3.5 w-3.5" /> .eml</a></span>
            ) : <span className="ml-auto text-2xs text-slate-500">{t("gesperrt bis Freigabe")}</span>}
          </li>
        ))}</ul>
      </div>
    </div>
  );
}
