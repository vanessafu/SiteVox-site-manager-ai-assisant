"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { AlertTriangle, FilePlus2, FileText, RotateCcw } from "lucide-react";
import { post, pct } from "@/lib/api";
import { BandDot, ConfidencePill, Elapsed, SphereChip, StatusChip } from "./ui";
import { useT } from "@/lib/i18n";

const FIELD_LABEL: Record<string, string> = {
  type: "Ereignistyp", sphere: "Risikosphäre", start: "Beginn", cause: "Ursache",
  affected_activities: "Betroffene Vorgänge", impact_estimate_days: "Auswirkung (AT)",
};
const SIGNAL_LABEL: Record<string, string> = {
  evidence: "Belege", asr: "ASR", consistency: "Konsistenz", retrieval: "Retrieval", rule: "Regel",
};

export function EventDetail({ e, onChanged }: { e: any; onChanged?: () => void }) {
  const { t } = useT();
  const [busy, setBusy] = useState(false);
  const confirm = async (s: string) => {
    setBusy(true);
    await post(`/api/events/${e.event_id}/sphere`, { sphere: s });
    setBusy(false);
    onChanged?.();
  };
  const reset = async () => {
    setBusy(true);
    await post(`/api/events/${e.event_id}/sphere/reset`);
    setBusy(false);
    onChanged?.();
  };
  const fields = e.confidence?.fields || {};
  return (
    <div className="space-y-3">
      <p>{e.description}</p>
      <div className="rounded-md bg-slate-50 p-2 text-xs">
        <div className="mb-1 flex items-center gap-2"><SphereChip sphere={e.sphere} confirmed={e.sphere_confirmed} /> <span className="text-slate-600">{t("Regel")}: {t(e.sphere_rule)}</span></div>
        {e.sphere_llm && (
          <p className="text-slate-600">{t("KI-Einschätzung")}: <b>{e.sphere_llm.party}</b> – {e.sphere_llm.rationale}</p>
        )}
        <p className="mt-1 font-medium text-warn-text">{t("Vorschlag, menschliche Bestätigung erforderlich.")}</p>
        <div className="mt-2 flex gap-1">
          {["AG", "AN", "neutral"].map((s) => (
            <button key={s} disabled={busy} onClick={() => confirm(s)} className={`btn-xs ${e.sphere === s && e.sphere_confirmed ? "bg-slate-900 text-white" : ""}`}>{t("{s} bestätigen", { s })}</button>
          ))}
          <button disabled={busy || !e.sphere_confirmed} onClick={reset} className="btn-xs disabled:opacity-40"
            title={t(e.sphere_confirmed ? "Bestätigung zurücknehmen – Sphäre wieder als Vorschlag des Regelwerks" : "Noch nicht bestätigt")}>
            <RotateCcw className="h-3.5 w-3.5" /> {t("Zurücksetzen")}
          </button>
        </div>
      </div>
      <div className="text-xs">
        <div className="mb-1 font-medium">{t("Empfehlung")}: {t(e.recommended_document.label)}{e.recommended_document.basis ? ` · ${e.recommended_document.basis}` : ""}</div>
        <p className="text-slate-600">{t(e.recommended_document.reason)}</p>
        <Elapsed from={e.detected_at} level={e.deadline.level} label={e.deadline.label} />
      </div>
      {e.impact_estimate_days?.value != null && (
        <div className="text-xs">{t("Auswirkung (Engine)")}: <b>{t("{n} AT", { n: e.impact_estimate_days.value })}</b> · {t("Konfidenz")} <ConfidencePill value={e.impact_estimate_days.confidence} /></div>
      )}
      {e.warnings?.length > 0 && (
        <ul className="space-y-1">{e.warnings.map((w: string) => <li key={w} className="flex gap-1 text-xs text-warn-text"><AlertTriangle className="h-3.5 w-3.5 shrink-0" />{t(w)}</li>)}</ul>
      )}
      <div>
        <div className="mb-1 text-2xs uppercase tracking-wide text-slate-500">{t("Feld-Konfidenz (ohne LLM-Selbstauskunft)")}</div>
        <table className="w-full text-2xs">
          <tbody>
            {Object.entries(fields).map(([k, f]: any) => (
              <tr key={k} className="border-t border-slate-100">
                <td className="py-1"><span className="inline-flex items-center gap-1"><BandDot b={f.band} />{t(FIELD_LABEL[k] || k)}</span></td>
                <td className="py-1 text-slate-600">{Object.entries(f.signals || {}).map(([s, v]: any) => `${t(SIGNAL_LABEL[s] || s)} ${pct(v)}`).join(" · ")}{f.reason ? ` · ${t(f.reason)}` : ""}</td>
                <td className="py-1 text-right"><ConfidencePill value={f.value} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function EventCard({ e, pid, onOpen, onChanged }: { e: any; pid: string; onOpen: () => void; onChanged?: () => void }) {
  const router = useRouter();
  const { t } = useT();
  const [busy, setBusy] = useState(false);
  const letterNeeded = e.recommended_document.requires_letter;
  const draft = async (ev: React.MouseEvent) => {
    ev.stopPropagation();
    setBusy(true);
    try {
      const l = await post(`/api/events/${e.event_id}/draft`);
      router.push(`/p/${pid}/schreiben/${l.letter_id}`);
    } finally {
      setBusy(false);
      onChanged?.();
    }
  };
  return (
    <div role="button" tabIndex={0} onClick={onOpen} onKeyDown={(k) => k.key === "Enter" && onOpen()}
      className={`card row-click flex items-start gap-3 p-3 ${letterNeeded ? "" : "opacity-70"}`}>
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{t(e.label)}{e.affected_activities?.length ? ` – ${e.affected_activities.map((a: string) => t(a)).join(", ")}` : ""}</span>
          {e.on_critical_path && <span className="pill bg-bad-soft text-bad-text">{t("kritischer Pfad")}</span>}
        </div>
        <div className="flex flex-wrap items-center gap-2 text-2xs text-slate-600">
          <SphereChip sphere={e.sphere} confirmed={e.sphere_confirmed} />
          <span>{letterNeeded ? `${t(e.recommended_document.label)} · ${e.recommended_document.basis}` : `${t(e.recommended_document.label)} · ${t("kein Schreiben an AG")}`}</span>
          {letterNeeded && e.status !== "sent" && <Elapsed from={e.detected_at} level={e.deadline.level} label={e.deadline.label} />}
        </div>
        {e.warnings?.map((w: string) => <div key={w} className="flex items-center gap-1 text-2xs text-warn-text"><AlertTriangle className="h-3.5 w-3.5" />{t(w)}</div>)}
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1.5">
        <ConfidencePill value={e.confidence?.overall} />
        {e.letter ? (
          <Link href={`/p/${pid}/schreiben/${e.letter.letter_id}`} onClick={(x) => x.stopPropagation()} className="btn-xs">
            <FileText className="h-3.5 w-3.5" /> <StatusChip status={e.letter.status} />
            {e.letter.open_issues > 0 && <span className="pill bg-bad-soft text-bad-text">{e.letter.open_issues} {t("rot")}</span>}
          </Link>
        ) : letterNeeded ? (
          <button className="btn-xs" disabled={busy} onClick={draft}><FilePlus2 className="h-3.5 w-3.5" /> {t("Entwurf erstellen")}</button>
        ) : (
          <span className="text-2xs text-slate-600">{t("nur Bautagebuch")}</span>
        )}
      </div>
    </div>
  );
}
