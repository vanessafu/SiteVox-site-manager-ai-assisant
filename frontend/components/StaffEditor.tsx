"use client";
import { useState } from "react";
import { Plus, Save, Trash2 } from "lucide-react";
import { put } from "@/lib/api";
import { useT } from "@/lib/i18n";

/** Personal je Kolonne für einen Tag bearbeiten (Ist / Soll). */
export default function StaffEditor({ pid, date, rows, onSaved }: { pid: string; date: string; rows: any[]; onSaved: () => void }) {
  const { t } = useT();
  const [list, setList] = useState(rows.map((r) => ({ crew: r.crew, present: r.present, planned: r.planned, isNew: false })));
  const [msg, setMsg] = useState<string | null>(null);
  const save = async (i: number, remove = false) => {
    const r = list[i];
    if (!r.crew.trim()) return;
    try {
      await put(`/api/projects/${pid}/staffing`, { date, crew: r.crew.trim(), present: remove ? null : Number(r.present), planned: Number(r.planned) });
      if (remove) setList(list.filter((_, j) => j !== i));
      setMsg(t("Gespeichert – Werte neu berechnet"));
      onSaved();
    } catch (e: any) {
      setMsg(e.message);
    }
  };
  const cell = "w-full rounded border border-slate-300 px-2 py-1 text-sm";
  return (
    <div className="space-y-2">
      <table className="w-full text-sm">
        <thead><tr className="text-left text-xs text-slate-600"><th>{t("Kolonne")}</th><th className="w-20">{t("Ist")}</th><th className="w-20">{t("Soll")}</th><th className="w-16" /></tr></thead>
        <tbody>
          {list.map((r, i) => (
            <tr key={i}>
              <td className="pr-1 py-1"><input className={cell} value={r.crew} disabled={!r.isNew} onChange={(e) => setList(list.map((x, j) => (j === i ? { ...x, crew: e.target.value } : x)))} /></td>
              <td className="pr-1"><input type="number" className={cell} value={r.present} onChange={(e) => setList(list.map((x, j) => (j === i ? { ...x, present: e.target.value } : x)))} /></td>
              <td className="pr-1"><input type="number" className={cell} value={r.planned} onChange={(e) => setList(list.map((x, j) => (j === i ? { ...x, planned: e.target.value } : x)))} /></td>
              <td className="whitespace-nowrap">
                <button className="btn-xs" onClick={() => save(i)} title={t("Speichern")}><Save className="h-3.5 w-3.5" /></button>
                <button className="btn-xs ml-1 text-bad-text" onClick={() => save(i, true)} title={t("Löschen")}><Trash2 className="h-3.5 w-3.5" /></button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button className="btn-xs" onClick={() => setList([...list, { crew: "", present: 0, planned: 0, isNew: true }])}><Plus className="h-3.5 w-3.5" /> {t("Kolonne hinzufügen")}</button>
      {msg && <p className="text-xs text-slate-600">{msg}</p>}
      <p className="text-2xs text-slate-600">{t("„Gesamt“ steuert die Kennzahl Personal; sonst Summe der Kolonnen.")}</p>
    </div>
  );
}
