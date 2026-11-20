"use client";
import { useState } from "react";
import { Save, Trash2 } from "lucide-react";
import { useT } from "@/lib/i18n";

export type FieldDef = {
  key: string;
  label: string;
  type?: "text" | "number" | "date" | "datetime" | "textarea" | "select" | "list" | "checkbox" | "effects";
  options?: { value: string; label: string }[];
  help?: string;
  required?: boolean;
};

// Ressourcen-Effekte als Zeilen "Ressource | Status | Start | Ende"
const toEffects = (s: string) =>
  s.split("\n").map((l) => l.split("|").map((x) => x.trim())).filter((p) => p[0])
    .map(([resource, status, start, end]) => ({ resource, status: status || "idle", start: start || "07:00", end: end || null }));
const fromEffects = (v: any[]) => (v || []).map((e) => [e.resource, e.status, e.start, e.end || ""].join(" | ")).join("\n");

function toInput(f: FieldDef, v: any) {
  if (v === null || v === undefined) return f.type === "checkbox" ? false : "";
  if (f.type === "list") return Array.isArray(v) ? v.join(", ") : v;
  if (f.type === "effects") return fromEffects(v);
  if (f.type === "datetime") return String(v).slice(0, 16);
  if (f.type === "date") return String(v).slice(0, 10);
  return v;
}

function fromInput(f: FieldDef, v: any, orig: any) {
  if (f.type === "number") return v === "" ? null : Number(v);
  if (f.type === "list") return String(v).split(",").map((x) => x.trim()).filter(Boolean);
  if (f.type === "effects") return toEffects(String(v));
  if (f.type === "datetime") {
    if (!v) return null;
    const tz = typeof orig === "string" && orig.length > 19 ? orig.slice(19) : "";
    return `${v}:00${tz}`;
  }
  if ((f.type === "date" || f.type === "text") && v === "") return null;
  return v;
}

/** Generisches Bearbeitungsformular (Drawer). Speichert über onSave; Werte werden serverseitig geprüft. */
export default function EditForm({ fields, initial, onSave, onDelete, deleteConfirm, note }: {
  fields: FieldDef[];
  initial: Record<string, any>;
  onSave: (patch: Record<string, any>) => Promise<any>;
  onDelete?: () => Promise<any>;
  deleteConfirm?: string;
  note?: string;
}) {
  const { t } = useT();
  const [vals, setVals] = useState<Record<string, any>>(() => Object.fromEntries(fields.map((f) => [f.key, toInput(f, initial[f.key])])));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const run = async (fn: () => Promise<any>, okText: string) => {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      setMsg({ ok: true, text: t(okText) });
    } catch (e: any) {
      setMsg({ ok: false, text: t(e.message) });
    } finally {
      setBusy(false);
    }
  };
  const save = () => {
    const patch: Record<string, any> = {};
    for (const f of fields) {
      const nv = fromInput(f, vals[f.key], initial[f.key]);
      if (JSON.stringify(nv) !== JSON.stringify(fromInput(f, toInput(f, initial[f.key]), initial[f.key]))) patch[f.key] = nv;
    }
    if (!Object.keys(patch).length) return setMsg({ ok: true, text: t("Keine Änderungen") });
    run(() => onSave(patch), "Gespeichert – Werte neu berechnet");
  };
  const input = "w-full rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-sm focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent-soft";
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save(); }}>
      {note && <p className="rounded-md bg-slate-100 p-2 text-xs text-slate-600">{t(note)}</p>}
      {fields.map((f) => (
        <label key={f.key} className={`block ${f.type === "checkbox" ? "flex items-center gap-2" : ""}`}>
          {f.type !== "checkbox" && <span className="mb-1 block text-xs font-medium text-slate-600">{t(f.label)}{f.required && " *"}</span>}
          {f.type === "textarea" || f.type === "effects" ? (
            <textarea className={`${input} min-h-[90px] ${f.type === "effects" ? "font-mono text-xs" : ""}`} value={vals[f.key]}
              onChange={(e) => setVals({ ...vals, [f.key]: e.target.value })} rows={f.type === "effects" ? 4 : 5} />
          ) : f.type === "select" ? (
            <select className={input} value={vals[f.key]} onChange={(e) => setVals({ ...vals, [f.key]: e.target.value })}>
              {f.options!.map((o) => <option key={o.value} value={o.value}>{t(o.label)}</option>)}
            </select>
          ) : f.type === "checkbox" ? (
            <>
              <input type="checkbox" className="h-4 w-4" checked={!!vals[f.key]} onChange={(e) => setVals({ ...vals, [f.key]: e.target.checked })} />
              <span className="text-sm">{t(f.label)}</span>
            </>
          ) : (
            <input className={input} required={f.required} step="any"
              type={f.type === "number" ? "number" : f.type === "date" ? "date" : f.type === "datetime" ? "datetime-local" : "text"}
              value={vals[f.key]} onChange={(e) => setVals({ ...vals, [f.key]: e.target.value })} />
          )}
          {f.help && <span className="mt-0.5 block text-2xs text-slate-500">{t(f.help)}</span>}
        </label>
      ))}
      {msg && <p className={`rounded-md p-2 text-xs ${msg.ok ? "bg-ok-soft text-ok-text" : "bg-bad-soft text-bad-text"}`}>{msg.text}</p>}
      <div className="flex items-center gap-2 pt-1">
        <button type="submit" className="btn-primary" disabled={busy}><Save className="h-4 w-4" /> {t("Speichern")}</button>
        {onDelete && (
          <button type="button" className="btn ml-auto text-bad-text" disabled={busy}
            onClick={() => window.confirm(t(deleteConfirm || "Wirklich löschen? (wird im Audit-Log protokolliert)")) && run(onDelete, "Gelöscht")}>
            <Trash2 className="h-4 w-4" /> {t("Löschen")}
          </button>
        )}
      </div>
    </form>
  );
}

// ---------------------------------------------------------------- gemeinsame Felddefinitionen
export const EVENT_TYPES = [
  ["material_delay", "Materiallieferverzug"], ["equipment_failure", "Geräteausfall"], ["weather_interruption", "Witterung"],
  ["worker_shortage", "Personalmangel"], ["third_party_interference", "Behinderung durch Dritte"], ["design_error", "Planungsfehler"],
  ["quality_defect", "Qualitätsmangel"], ["additional_work", "Zusätzliche Leistung"],
  ["planlieferverzug", "Planlieferverzug / fehlende Mitwirkung"], ["leistungsaenderung", "Leistungsänderung (AG-Anordnung)"],
].map(([value, label]) => ({ value, label }));

export const EVENT_FIELDS: FieldDef[] = [
  { key: "type", label: "Ereignistyp", type: "select", options: EVENT_TYPES },
  { key: "description", label: "Beschreibung", type: "textarea" },
  { key: "cause", label: "Ursache", type: "text" },
  { key: "start", label: "Beginn", type: "datetime" },
  { key: "end", label: "Ende", type: "datetime" },
  { key: "affected_activities", label: "Betroffene Vorgänge", type: "list", help: "Kommagetrennt, z. B. Bewehrung BP, Betonage BP" },
  { key: "blocked_until", label: "Blockiert bis (für Prognose)", type: "date" },
  { key: "resource_effects", label: "Tagesverlauf: Gerät/Kolonne", type: "effects", help: "Je Zeile: Ressource | work/restricted/idle/planned_not_started | Start | Ende" },
  { key: "work_started", label: "Ausführung bereits begonnen (Zusatzleistung)", type: "checkbox" },
];

export const ACTIVITY_FIELDS: FieldDef[] = [
  { key: "name", label: "Vorgang", type: "text", required: true },
  { key: "kind", label: "Typ", type: "select", options: [{ value: "task", label: "Vorgang" }, { value: "milestone", label: "Meilenstein (Vertragsfrist)" }] },
  { key: "start", label: "Anfang", type: "date", required: true },
  { key: "finish", label: "Ende", type: "date", required: true },
  { key: "qty", label: "Menge", type: "number" },
  { key: "unit", label: "Einheit", type: "text" },
  { key: "lv_pos", label: "LV-Position", type: "text" },
  { key: "lv_sum", label: "LV-Summe (€)", type: "number", help: "Gewichtung für den Gesamtfortschritt" },
  { key: "preds", label: "Vorgänger", type: "text", help: "z. B. A40FS-1; A30SS+4 (FS/SS, Lag in Arbeitstagen)" },
  { key: "aliases", label: "Synonyme (für Spracherkennung)", type: "text", help: "Semikolon-getrennt" },
];

export const predsToString = (p: any[]) => (p || []).map((x) => `${x.id}${x.type}${x.lag ? (x.lag > 0 ? `+${x.lag}` : x.lag) : ""}`).join("; ");
