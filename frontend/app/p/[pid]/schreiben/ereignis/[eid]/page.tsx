"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { ArrowLeft, BookOpenCheck, FilePlus2, FileText, Pencil, X } from "lucide-react";
import { api, dLong, post, useApi } from "@/lib/api";
import { EventDetail } from "@/components/EventCard";
import { EvidenceSources } from "@/components/EvidenceViewer";
import EditForm, { EVENT_FIELDS } from "@/components/EditForm";
import { ConfidencePill, StatusChip } from "@/components/ui";
import { useT } from "@/lib/i18n";

/** Ereignis-Status (intern) → Anzeige. */
const EVENT_STATUS: Record<string, string> = {
  logged: "im Bautagebuch dokumentiert", draft: "Entwurf", released: "Geprüft", sent: "Versendet", open: "offen",
};

/** Eigene Seite je Ereignis unter „Schreiben“ – auch für AN-Ereignisse ohne Schreiben an den AG. */
export default function EventPage() {
  const { pid, eid } = useParams<{ pid: string; eid: string }>();
  const { data: e, error, reload } = useApi<any>(`/api/events/${eid}`);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const router = useRouter();
  const { t } = useT();
  if (error) return <div className="p-6 text-bad-text">{error}</div>;
  if (!e) return <div className="p-6 text-slate-500">{t("lädt …")}</div>;
  const letterNeeded = e.recommended_document.requires_letter;

  const draft = async () => {
    setBusy(true);
    try {
      const l = await post(`/api/events/${e.event_id}/draft`);
      router.push(`/p/${pid}/schreiben/${l.letter_id}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="sticky top-0 z-20 border-b border-slate-200 bg-white">
        <div className="flex flex-wrap items-center gap-2 px-4 py-2">
          <Link href={`/p/${pid}/schreiben`} className="rounded p-1 hover:bg-slate-100"><ArrowLeft className="h-[18px] w-[18px]" /></Link>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2 font-semibold">
              {t(e.label)}{e.affected_activities?.length ? ` – ${e.affected_activities.map((a: string) => t(a)).join(", ")}` : ""}
              {e.on_critical_path && <span className="pill bg-bad-soft text-bad-text">{t("kritischer Pfad")}</span>}
              <StatusChip status={EVENT_STATUS[e.status] || e.status} />
            </div>
            <div className="text-2xs text-slate-600">{e.event_id} · {dLong(e.start)} {e.start.slice(11, 16)}{e.end ? `–${e.end.slice(11, 16)}` : ""}</div>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <ConfidencePill value={e.confidence?.overall} />
            {e.letter ? (
              <Link className="btn-primary" href={`/p/${pid}/schreiben/${e.letter.letter_id}`}>
                <FileText className="h-[18px] w-[18px]" /> {t(e.recommended_document.label)} {e.letter.letter_id} · {t(e.letter.status)}
              </Link>
            ) : letterNeeded ? (
              <button className="btn-primary" disabled={busy} onClick={draft}><FilePlus2 className="h-[18px] w-[18px]" /> {t("Entwurf erstellen")}</button>
            ) : (
              <span className="pill border border-slate-200 bg-slate-50 text-slate-600"><BookOpenCheck className="mr-1 inline h-3.5 w-3.5" />{t("nur Bautagebuch")} · {t("kein Schreiben an AG")}</span>
            )}
            <button className="btn" onClick={() => setEditing(!editing)}>
              {editing ? <X className="h-[18px] w-[18px]" /> : <Pencil className="h-[18px] w-[18px]" />} {t(editing ? "Abbrechen" : "Ereignis bearbeiten")}
            </button>
          </div>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
        <div className="space-y-4 overflow-y-auto border-r border-slate-200 p-4">
          {editing ? (
            <div className="card p-4">
              <EditForm fields={EVENT_FIELDS} initial={{ ...e, work_started: e.attrs?.work_started }}
                note="Risikosphäre, Empfehlung und Konfidenz werden nach dem Speichern regelbasiert neu berechnet."
                onSave={async (patch) => { await api(`/api/events/${e.event_id}`, { method: "PATCH", body: JSON.stringify(patch) }); setEditing(false); reload(); }}
                onDelete={async () => { await api(`/api/events/${e.event_id}`, { method: "DELETE" }); router.push(`/p/${pid}/schreiben`); }} />
            </div>
          ) : (
            <div className="card p-4 text-sm"><EventDetail e={e} onChanged={reload} /></div>
          )}
          {e.cause && <div className="card p-4 text-sm"><div className="mb-1 text-2xs uppercase tracking-wide text-slate-500">{t("Ursache")}</div>{e.cause}</div>}
          <details className="card p-3 text-xs">
            <summary className="cursor-pointer font-medium">{t("Audit-Log ({n})", { n: e.audit?.length || 0 })}</summary>
            <ul className="mt-2 space-y-1">{(e.audit || []).map((a: any) => <li key={a.id} className="text-slate-600"><span className="font-mono text-slate-500">{a.ts.slice(0, 16).replace("T", " ")}</span> {a.actor} · {a.action} {a.note && `· ${a.note}`}</li>)}</ul>
          </details>
        </div>
        <aside className="space-y-3 overflow-y-auto bg-slate-50 p-4">
          <div className="text-2xs uppercase tracking-wide text-slate-500">{t("Belege – je Quelle einmal")}</div>
          <EvidenceSources ids={e.evidence} />
        </aside>
      </div>
    </div>
  );
}
