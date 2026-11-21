"use client";
/**
 * Bericht-Tabelle (Personal § 2, Geräte § 3) mit direkter Bearbeitung je Zeile.
 * Speichert über PUT /api/projects/{pid}/report-rows → gilt für Dashboard UND PDF/DOCX (daily_report.build).
 * Von Hand gesetzte Felder werden markiert und lassen sich auf den berechneten Wert zurücksetzen.
 */
import { Fragment, ReactNode, useState } from "react";
import { Check, Pencil, Plus, RotateCcw, Trash2, X } from "lucide-react";
import { num, put } from "@/lib/api";
import { useT } from "@/lib/i18n";

export type Col = {
  key: string;
  label: string;
  type: "text" | "int" | "num" | "spans" | "select";
  options?: string[];
  right?: boolean;
  show?: (r: any) => ReactNode; // Anzeige (Standard: Wert)
};

const spansToText = (v: any[]) => (v || []).map((s) => (s.to ? `${s.from}–${s.to}` : `${s.from}–`)).join(", ");
const textToSpans = (s: string) =>
  s.split(",").map((x) => x.trim()).filter(Boolean).map((x) => {
    const [from, to] = x.split(/\s*[–-]\s*/);
    return { from: from?.trim(), to: to?.trim() || null };
  }).filter((x) => x.from);

function toForm(c: Col, v: any) {
  if (c.type === "spans") return spansToText(v);
  return v === null || v === undefined ? "" : String(v);
}
function fromForm(c: Col, v: string) {
  if (c.type === "spans") return textToSpans(v);
  if (c.type === "int" || c.type === "num") return v.trim() === "" ? null : Number(v.replace(",", "."));
  return v.trim() === "" ? null : v;
}

export default function ReportTable({ pid, date, section, keyField, keyLabel, cols, rows, footer, actions, onSaved, addLabel }: {
  pid: string; date: string; section: "workforce" | "equipment"; keyField: string; keyLabel: string; cols: Col[];
  rows: any[]; footer?: ReactNode; actions: (r: any) => ReactNode; onSaved: () => void; addLabel: string;
}) {
  const { t } = useT();
  const [edit, setEdit] = useState<string | null>(null); // key der Zeile im Bearbeitungsmodus ("" = neue Zeile)
  const [form, setForm] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const start = (r: any | null) => {
    setErr(null);
    setEdit(r ? r[keyField] : "");
    setForm(Object.fromEntries([[keyField, r ? r[keyField] : ""], ...cols.map((c) => [c.key, r ? toForm(c, r[c.key]) : ""])]));
  };
  const send = async (key: string, action: "set" | "delete" | "reset", data?: any) => {
    setBusy(true);
    setErr(null);
    try {
      await put(`/api/projects/${pid}/report-rows`, { date, section, key, action, data });
      setEdit(null);
      onSaved();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };
  const save = (orig: any | null) => {
    const key = (orig ? orig[keyField] : form[keyField] || "").trim();
    if (!key) return setErr(t("Name fehlt"));
    // nur geänderte Felder senden → übrige bleiben berechnet
    const data: Record<string, any> = {};
    for (const c of cols) {
      if (orig && form[c.key] === toForm(c, orig[c.key])) continue;
      data[c.key] = fromForm(c, form[c.key]);
    }
    if (!Object.keys(data).length && orig) return setEdit(null);
    send(key, "set", data);
  };

  const inp = "w-full min-w-[3.5rem] rounded border border-slate-300 px-1.5 py-0.5 text-sm";
  const th = "px-2 py-1.5 font-medium";
  const td = "px-2 py-1.5 align-top";
  const editor = (orig: any | null) => (
    <tr className="border-t border-slate-100 bg-accent-soft/40">
      <td className={td}>
        {orig ? <span className="font-medium">{t(orig[keyField])}</span>
          : <input autoFocus className={inp} placeholder={t(keyLabel)} value={form[keyField] || ""} onChange={(e) => setForm({ ...form, [keyField]: e.target.value })} />}
      </td>
      {cols.map((c) => (
        <td key={c.key} className={td}>
          {c.type === "select" ? (
            <select className={inp} value={form[c.key] || ""} onChange={(e) => setForm({ ...form, [c.key]: e.target.value })}>
              {c.options!.map((o) => <option key={o} value={o}>{t(o)}</option>)}
            </select>
          ) : (
            <input className={`${inp} ${c.right ? "text-right" : ""}`} inputMode={c.type === "int" || c.type === "num" ? "decimal" : undefined}
              placeholder={c.type === "spans" ? "10:00–13:30" : ""} value={form[c.key] || ""}
              onChange={(e) => setForm({ ...form, [c.key]: e.target.value })}
              onKeyDown={(e) => { if (e.key === "Enter") save(orig); if (e.key === "Escape") { e.stopPropagation(); setEdit(null); } }} />
          )}
        </td>
      ))}
      <td className={`${td} whitespace-nowrap text-right`}>
        <button className="btn-xs" disabled={busy} onClick={() => save(orig)} title={t("Speichern")}><Check className="h-3.5 w-3.5" /></button>
        <button className="btn-xs ml-1" onClick={() => setEdit(null)} title={t("Abbrechen")}><X className="h-3.5 w-3.5" /></button>
        {orig && <button className="btn-xs ml-1 text-bad-text" disabled={busy} title={t("Zeile entfernen")}
          onClick={() => confirm(t("Zeile „{n}“ aus dem Bericht entfernen?", { n: t(orig[keyField]) })) && send(orig[keyField], "delete")}><Trash2 className="h-3.5 w-3.5" /></button>}
      </td>
    </tr>
  );

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-slate-600"><tr>
          <th className={th}>{t(keyLabel)}</th>
          {cols.map((c) => <th key={c.key} className={`${th} ${c.right ? "text-right" : ""}`}>{t(c.label)}</th>)}
          <th className={`${th} text-right`}>{t("Belege")}</th>
        </tr></thead>
        <tbody>
          {rows.map((r) => edit === r[keyField] ? <Fragment key={r[keyField]}>{editor(r)}</Fragment> : (
            <tr key={r[keyField]} className="group border-t border-slate-100 hover:bg-slate-50" onDoubleClick={() => start(r)}>
              <td className={td}>
                {t(r[keyField])}
                {r.added && <span className="pill ml-1 bg-slate-100 text-slate-600">{t("manuell")}</span>}
                {r.company && <div className="text-2xs text-slate-600">{r.company}</div>}
              </td>
              {cols.map((c) => {
                const manual = r.manual?.includes(c.key) && !r.added;
                return (
                  <td key={c.key} className={`${td} ${c.right ? "text-right tabular-nums" : ""} ${manual ? "bg-accent-soft/60" : ""}`}
                    title={manual ? t("manuell geändert") : undefined}>
                    {c.show ? c.show(r) : c.type === "spans" ? (spansToText(r[c.key]) || "–")
                      : c.type === "num" ? (r[c.key] === null || r[c.key] === undefined ? "–" : num(r[c.key]))
                      : c.type === "select" ? t(r[c.key] ?? "–") : (r[c.key] ?? "–")}
                  </td>
                );
              })}
              <td className={`${td} whitespace-nowrap text-right`}>
                <button className="btn-xs mr-1" onClick={() => start(r)} title={t("Bearbeiten")}><Pencil className="h-3.5 w-3.5" /></button>
                {r.manual?.length > 0 && !r.added && (
                  <button className="btn-xs mr-1" disabled={busy} onClick={() => send(r[keyField], "reset")} title={t("Manuelle Änderung verwerfen")}><RotateCcw className="h-3.5 w-3.5" /></button>
                )}
                {actions(r)}
              </td>
            </tr>
          ))}
          {edit === "" && editor(null)}
          {footer}
        </tbody>
      </table>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <button className="btn-xs" onClick={() => start(null)} disabled={edit !== null}><Plus className="h-3.5 w-3.5" /> {t(addLabel)}</button>
        <span className="text-2xs text-slate-600">{t("Doppelklick auf eine Zeile = bearbeiten · blau hinterlegt = manuell geändert · gilt auch für den PDF-Bericht")}</span>
        {err && <span className="text-xs text-bad-text">{err}</span>}
      </div>
    </div>
  );
}
