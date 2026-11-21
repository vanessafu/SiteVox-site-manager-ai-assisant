"use client";
/**
 * „Aus dem Vertrag erkannt“: Angaben, die beim Hochladen des Vertrags gelesen wurden. Leere Stammdatenfelder füllt
 * SiteVox automatisch; abweichende Werte übernimmt nur die Bauleitung per Klick (mit Fundstelle).
 */
import { useState } from "react";
import { Check, FileSearch } from "lucide-react";
import { dLong, post, useApi } from "@/lib/api";
import { useT } from "@/lib/i18n";

const LABEL: Record<string, string> = {
  contract_no: "Vertragsnummer", contract_date: "Vertragsdatum", title: "Bauvorhaben", address: "Adresse Baustelle",
  contract_basis: "Vertragsgrundlage", "client.name": "Auftraggeber", "client.address": "Adresse AG",
  "client.representative": "Bevollmächtigter Vertreter", "client.representative_role": "Funktion",
  "client.email": "E-Mail AG", "client.phone": "Telefon AG", parties: "Beteiligte ohne Vollmacht", milestones: "Vertragsfristen",
};

const show = (k: string, v: any) =>
  v == null || v === "" ? "–"
    : k === "contract_date" ? dLong(v)
    : k === "parties" ? v.map((p: any) => p.name).join(", ")
    : k === "milestones" ? v.map((m: any) => `${m.name} ${dLong(m.date)}`).join(", ")
    : String(v);

export default function ContractInfo({ pid, onApplied }: { pid: string; onApplied: () => void }) {
  const { t } = useT();
  const { data, reload } = useApi<any>(`/api/projects/${pid}/contract-info`);
  const [busy, setBusy] = useState(false);
  const rows = (data?.fields || []).filter((r: any) => r.state !== "same");
  if (!data || !data.fields.length) return null;
  const apply = async (keys: string[]) => {
    setBusy(true);
    try { await post(`/api/projects/${pid}/contract-info/apply`, { keys }); reload(); onApplied(); } finally { setBusy(false); }
  };
  return (
    <div className="mb-4 rounded-md border border-accent bg-accent-soft/50 p-3 text-sm">
      <div className="mb-1 flex items-center gap-2 font-semibold text-accent-text">
        <FileSearch className="h-4 w-4" /> {t("Aus dem Vertrag erkannt")}
        {rows.length > 1 && <button className="btn-xs ml-auto" disabled={busy} onClick={() => apply(rows.map((r: any) => r.key))}>{t("Alle übernehmen")}</button>}
      </div>
      {!rows.length ? <p className="text-xs text-slate-600">{t("Alle erkannten Angaben stimmen mit den Stammdaten überein.")}</p> : (
        <ul className="space-y-1.5">
          {rows.map((r: any) => (
            <li key={r.key} className="rounded bg-white p-2">
              <div className="flex items-start gap-2">
                <div className="min-w-0 flex-1">
                  <div className="text-xs text-slate-600">{t(LABEL[r.key] || r.key)}</div>
                  <div className="font-medium">{show(r.key, r.value)}</div>
                  {r.state === "differs" && <div className="text-xs text-warn-text">{t("bisher")}: {show(r.key, r.current)}</div>}
                </div>
                <button className="btn-xs" disabled={busy} onClick={() => apply([r.key])}><Check className="h-3.5 w-3.5" /> {t("Übernehmen")}</button>
              </div>
              <div className="mt-1 text-2xs italic text-slate-500">„{r.quote}“ · {r.doc_title}, S. {r.page}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
