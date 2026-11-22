"use client";
/**
 * Wissensbasis-Dokument: 1) Original (PDF/Bild im Browser), 2) daraus gelesene Angaben, 3) Volltext (eingeklappt).
 * Angaben kommen aus GET /api/documents/{id} → info (regelbasiert: Bautagesbericht, Vertrag).
 */
import { Fragment, ReactNode, useState } from "react";
import { AlertTriangle, CalendarDays, ChevronDown, ChevronRight, CloudRain, Download, ExternalLink, FileSearch, Truck, Users, Wrench } from "lucide-react";
import { dLong } from "@/lib/api";
import { useT } from "@/lib/i18n";

const CONTRACT_LABEL: Record<string, string> = {
  contract_no: "Vertragsnummer", contract_date: "Vertragsdatum", title: "Bauvorhaben", address: "Adresse Baustelle",
  contract_basis: "Vertragsgrundlage", "client.name": "Auftraggeber", "client.address": "Adresse AG",
  "client.representative": "Bevollmächtigter Vertreter", "client.representative_role": "Funktion",
  "client.email": "E-Mail AG", "client.phone": "Telefon AG", parties: "Beteiligte ohne Vollmacht", milestones: "Vertragsfristen",
};

const showVal = (k: string, v: any) =>
  v == null || v === "" ? "–"
    : k === "contract_date" ? dLong(v)
    : k === "parties" ? v.map((p: any) => p.name).join(", ")
    : k === "milestones" ? v.map((m: any) => `${m.name} ${dLong(m.date)}`).join(", ")
    : String(v);

function Kpi({ icon: Icon, label, value, bad }: { icon: any; label: string; value: ReactNode; bad?: boolean }) {
  return (
    <div className={`rounded-lg border px-3 py-2 ${bad ? "border-bad bg-bad-soft/50" : "border-slate-200"}`}>
      <div className="flex items-center gap-1.5 text-2xs uppercase tracking-wide text-slate-500"><Icon className="h-3.5 w-3.5" /> {label}</div>
      <div className={`mt-0.5 text-sm font-semibold ${bad ? "text-bad-text" : ""}`}>{value}</div>
    </div>
  );
}

function MiniTable({ t: tbl }: { t: { header: string[]; rows: string[][] } }) {
  const n = tbl.header.length;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead><tr>{tbl.header.map((h, i) => <th key={i} className="border-b border-slate-300 px-2 py-1 text-left font-medium text-slate-600">{h}</th>)}</tr></thead>
        <tbody>{tbl.rows.map((r, j) => {
          // kürzere Zeilen (z. B. „Summe“ ohne Gewerk) rechtsbündig an die Spalten anlegen
          const cells = r.length < n ? [r[0], ...Array(n - r.length).fill(""), ...r.slice(1)] : r;
          return <tr key={j} className={`border-b border-slate-100 ${/^summe/i.test(r[0]) ? "font-semibold" : ""}`}>{cells.map((c, i) => <td key={i} className="px-2 py-1 align-top">{c}</td>)}</tr>;
        })}</tbody>
      </table>
    </div>
  );
}

function DailyReportInfo({ info }: { info: any }) {
  const { t } = useT();
  const s = info.summary || {};
  const [open, setOpen] = useState<Record<number, boolean>>({});
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
        <Kpi icon={CalendarDays} label={t("Berichtstag")} value={info.date ? `${dLong(info.date)}${info.report_no ? ` · Nr. ${info.report_no}` : ""}` : "–"} />
        <Kpi icon={CloudRain} label={t("Witterung")} value={s.weather ? `${s.weather[Object.keys(s.weather)[0]]} · ${s.weather[Object.keys(s.weather)[1]] || ""}` : "–"} />
        <Kpi icon={Users} label={t("Personal Ist / Soll")} value={s.staff ? `${s.staff.actual ?? "–"} / ${s.staff.planned ?? "–"}${s.staff.hours ? ` · ${s.staff.hours} h` : ""}` : "–"}
          bad={s.staff && s.staff.actual != null && s.staff.planned != null && s.staff.actual < s.staff.planned} />
        <Kpi icon={Wrench} label={t("Geräte gestört")} value={s.equipment_down ? (s.equipment_down.length ? s.equipment_down.join(", ") : t("keine")) : "–"} bad={!!s.equipment_down?.length} />
        <Kpi icon={Truck} label={t("Lieferungen")} value={s.deliveries ?? "–"} />
        <Kpi icon={AlertTriangle} label={t("Vorkommnisse")} value={s.events?.length ?? 0} bad={!!s.events?.length} />
      </div>

      {(s.delayed_activities?.length > 0 || s.milestones_at_risk?.length > 0) && (
        <div className="rounded-lg border border-bad bg-bad-soft/40 p-3 text-sm">
          {s.delayed_activities?.length > 0 && <div><b>{t("Verzug")}:</b> {s.delayed_activities.join(", ")}</div>}
          {s.milestones_at_risk?.map((m: string) => <div key={m} className="mt-1 text-bad-text">{m}</div>)}
        </div>
      )}

      {s.events?.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-2xs font-medium uppercase tracking-wide text-slate-500">{t("Besondere Vorkommnisse")}</div>
          {s.events.map((e: any) => (
            <div key={e.id} className="flex flex-wrap items-center gap-2 rounded border border-slate-200 px-3 py-1.5 text-sm">
              <span className="font-mono text-2xs text-slate-500">{e.id}</span>
              <b>{e.title}</b>
              <span className="text-xs text-slate-600">{e.when}</span>
              {e.sphere && <span className={`pill ${e.sphere === "AG" ? "bg-warn-soft text-warn-text" : "bg-slate-100 text-slate-700"}`}>{t("Sphäre")} {e.sphere}</span>}
              {e.measure && <span className="text-xs">→ {e.measure}</span>}
              {e.status && <span className="ml-auto text-2xs text-slate-500">{e.status}</span>}
            </div>
          ))}
        </div>
      )}

      {info.head?.length > 0 && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-0.5 rounded-lg bg-slate-50 p-3 text-xs sm:grid-cols-[auto_1fr_auto_1fr]">
          {info.head.map((h: any, i: number) => (<Fragment key={i}><dt className="text-slate-500">{h.label}</dt><dd>{h.value}</dd></Fragment>))}
        </dl>
      )}

      <div className="divide-y divide-slate-100 rounded-lg border border-slate-200">
        {info.sections.filter((x: any) => x.tables.length || x.notes.length || x.fields.length).map((x: any) => (
          <div key={x.no}>
            <button className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm font-medium hover:bg-slate-50" onClick={() => setOpen({ ...open, [x.no]: !open[x.no] })}>
              {open[x.no] ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />} {x.no} {x.title}
              <span className="ml-auto text-2xs font-normal text-slate-500">{x.tables.reduce((n: number, tb: any) => n + tb.rows.length, 0) || ""}</span>
            </button>
            {open[x.no] && (
              <div className="space-y-2 px-3 pb-3">
                {x.fields.map((f: any) => <div key={f.label} className="text-xs"><span className="text-slate-500">{f.label}:</span> {f.value}</div>)}
                {x.tables.map((tb: any, i: number) => <MiniTable key={i} t={tb} />)}
                {x.notes.map((n: string) => <p key={n} className="text-xs text-slate-600">{n}</p>)}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function ContractFields({ info }: { info: any }) {
  const { t } = useT();
  if (!info.fields.length) return <p className="text-sm text-slate-600">{t("Keine Vertragsangaben erkannt.")}</p>;
  return (
    <dl className="divide-y divide-slate-100 text-sm">
      {info.fields.map((f: any) => (
        <div key={f.key} className="grid gap-1 py-1.5 sm:grid-cols-[12rem_1fr]">
          <dt className="text-xs text-slate-500">{t(CONTRACT_LABEL[f.key] || f.key)}</dt>
          <dd>{showVal(f.key, f.value)}<div className="text-2xs text-slate-500">„{f.quote}“ · {t("S. {n}", { n: f.page })}</div></dd>
        </div>
      ))}
    </dl>
  );
}

export function DocOriginal({ doc }: { doc: any }) {
  const { t } = useT();
  if (!doc.has_file) return null;
  const url = `/api/documents/${doc.doc_id}/file`;
  const f = String(doc.file || "").toLowerCase();
  const pdf = f.endsWith(".pdf");
  const img = /\.(png|jpe?g|webp|gif|bmp|tiff?)$/.test(f);
  return (
    <section className="space-y-2">
      <div className="flex items-center gap-2 text-2xs font-medium uppercase tracking-wide text-slate-500">
        {t("Original")}
        <a className="btn-xs ml-auto normal-case tracking-normal" href={url} target="_blank" rel="noreferrer"><ExternalLink className="h-3.5 w-3.5" /> {t("In neuem Tab")}</a>
        <a className="btn-xs normal-case tracking-normal" href={url} download><Download className="h-3.5 w-3.5" /> {t("Herunterladen")}</a>
      </div>
      {pdf ? <iframe src={url} title={doc.title} className="h-[75vh] w-full rounded-lg border border-slate-200 bg-slate-100" />
        : img ? <img src={url} alt={doc.title} className="max-h-[75vh] rounded-lg border border-slate-200" />
        : <p className="text-xs text-slate-600">{t("Für dieses Format keine Vorschau – bitte herunterladen.")}</p>}
    </section>
  );
}

export default function DocInfo({ doc }: { doc: any }) {
  const { t } = useT();
  const info = doc.info;
  if (!info) return null;
  return (
    <section className="space-y-2">
      <div className="flex items-center gap-2 text-2xs font-medium uppercase tracking-wide text-slate-500">
        <FileSearch className="h-3.5 w-3.5" /> {t(info.type === "vertrag" ? "Aus dem Vertrag gelesen" : "Aus dem Bautagesbericht gelesen")}
        <span className="normal-case tracking-normal text-slate-400">· {t("regelbasiert, bitte am Original prüfen")}</span>
      </div>
      {info.type === "vertrag" ? <ContractFields info={info} /> : <DailyReportInfo info={info} />}
    </section>
  );
}

