"use client";
/**
 * Dashboard = heutiger Bautagesbericht zum Anklicken. Die Abschnitte spiegeln den Bericht (gleiche Daten aus
 * GET /api/projects/{pid}/report = daily_report.build, also dieselbe Funktion wie PDF/DOCX); Belege, die im
 * Bericht nicht mehr gedruckt werden, öffnen sich hier in der rechten Seitenleiste.
 * Mit `day` zeigt dieselbe Ansicht einen früheren Berichtstag (Verlauf).
 */
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import {
  AlertCircle, AlertTriangle, ArrowRight, Building2, CalendarDays, Camera, ChevronLeft, ChevronRight, History, CloudRain, FileDown, FolderOpen, HardHat, ListChecks, Mic,
  NotebookPen, Pencil, TrendingUp, Truck, Users, Wrench,
} from "lucide-react";
import { dLong, dShort, num, pct, useApi } from "@/lib/api";
import { LangToggle, locale, useT } from "@/lib/i18n";
import { useDrawer } from "@/components/Drawer";
import { EvidenceSources } from "@/components/EvidenceViewer";
import EventCard from "@/components/EventCard";
import ReportTable from "@/components/ReportTable";

type T = (s: string, v?: Record<string, any>) => string;

// Ampel wie im Bericht/Bullet: < 60 % rot, < 90 % gelb, sonst grün
const ratioCls = (r?: number | null) =>
  r === null || r === undefined ? "bg-slate-300" : r < 0.6 ? "bg-bad" : r < 0.9 ? "bg-warn" : "bg-ok";
const span = (s: { from?: string; to?: string }, t: T) => (s.to ? `${s.from}–${s.to}` : t("seit {a}", { a: s.from }));
/** große Datumsanzeige im Kopf: „Freitag, 20. November 2026“ */
const bigDate = (iso: string) =>
  new Date(iso + "T12:00:00").toLocaleDateString(locale(), { weekday: "long", day: "numeric", month: "long", year: "numeric" });
const URGENCY: Record<string, number> = { critical: 0, warn: 1, info: 3, ok: 4, none: 5, done: 6 };

/** Knopf „Belege (n)“ → Seitenleiste mit den Belegen der Zeile */
function EvidenceBtn({ ids, title }: { ids: string[]; title: string }) {
  const drawer = useDrawer();
  const { t } = useT();
  return (
    <button className="btn-xs" disabled={!ids?.length} title={t("Belege öffnen")}
      onClick={(e) => { e.stopPropagation(); drawer.open({ title, subtitle: t("Belege"), evidence: ids, showEvidence: true }); }}>
      <FolderOpen className="h-3.5 w-3.5" /> {ids?.length || 0}
    </button>
  );
}

function Section({ id, icon: Icon, title, right, children }: { id?: string; icon: any; title: string; right?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section id={id} className="card scroll-mt-4 p-4">
      <div className="section-head">
        <h2 className="flex items-center gap-2 font-semibold"><Icon className="h-[18px] w-[18px]" /> {title}</h2>
        {right}
      </div>
      {children}
    </section>
  );
}

const th = "px-2 py-1.5 font-medium";
const td = "px-2 py-1.5 align-top";

/** Pfeilförmiger Fortschrittsbalken: Ist / Tagessoll */
function Chevron({ ratio }: { ratio: number | null }) {
  const w = Math.max(0, Math.min(1, ratio ?? 0)) * 100;
  const clip = "polygon(0 0, calc(100% - 12px) 0, 100% 50%, calc(100% - 12px) 100%, 0 100%, 12px 50%)";
  return (
    <div className="relative h-6 bg-slate-100" style={{ clipPath: clip }}>
      <div className={`absolute inset-y-0 left-0 ${ratioCls(ratio)}`} style={{ width: `${w}%` }} />
    </div>
  );
}

/** Seitenleiste „Captures“: senkrechte Zeitleiste der fortschrittsbezogenen Erfassungen des Tages */
function CaptureTimeline({ caps }: { caps: any[] }) {
  const { t } = useT();
  const [big, setBig] = useState<string | null>(null);
  if (!caps.length) return <p className="text-slate-600">{t("Keine Fortschritts-Erfassungen an diesem Tag.")}</p>;
  return (
    <ol className="relative ml-3 space-y-4 border-l-2 border-slate-200 pl-5">
      {caps.map((c) => (
        <li key={c.capture_id} className="relative">
          <span className="absolute -left-[31px] top-0.5 flex h-5 w-5 items-center justify-center rounded-full border-2 border-white bg-slate-800 text-white">
            {c.kind === "photo" ? <Camera className="h-3 w-3" /> : <Mic className="h-3 w-3" />}
          </span>
          <div className="text-xs font-semibold tabular-nums">{c.time} <span className="font-normal text-slate-600">· {c.title}</span></div>
          {c.kind === "photo" && c.file ? (
            <div className="mt-1">
              <button onClick={() => setBig(big === c.capture_id ? null : c.capture_id)} title={t("Vergrößern")}>
                <img src={`/files/${c.file}`} alt={c.title || ""}
                  className={`rounded border object-cover transition-all ${big === c.capture_id ? "w-full" : "h-24 w-36"}`} />
              </button>
              <p className="mt-1 text-xs text-slate-700">{c.summary || c.excerpt}</p>
            </div>
          ) : (
            <p className="mt-1 text-xs italic text-slate-700">„{c.excerpt}{c.excerpt?.length >= 280 ? " …" : ""}“</p>
          )}
          {c.evidence_ids?.length > 0 && (
            <details className="mt-1 text-xs">
              <summary className="cursor-pointer text-accent-text">{t("Belege öffnen")} ({c.evidence_ids.length})</summary>
              <div className="mt-2"><EvidenceSources ids={c.evidence_ids} /></div>
            </details>
          )}
        </li>
      ))}
    </ol>
  );
}

export default function DashboardView({ day }: { day?: string }) {
  const { pid } = useParams<{ pid: string }>();
  const { data: d, error, reload } = useApi<any>(`/api/projects/${pid}/dashboard${day ? `?date=${day}` : ""}`, day ? undefined : 20_000);
  const { data: rep, reload: reloadRep } = useApi<any>(d ? `/api/projects/${pid}/report?date=${d.date}` : null, 20_000);
  const { data: master, reload: reloadMaster } = useApi<any>(`/api/projects/${pid}/master`);
  const { data: days } = useApi<any[]>(day ? `/api/projects/${pid}/days` : null);
  const drawer = useDrawer();
  const router = useRouter();
  const { t } = useT();
  const idx = (days || []).findIndex((x) => x.date === day);
  const older = idx >= 0 ? days![idx + 1]?.date : undefined; // Liste ist neueste zuerst
  const newer = idx > 0 ? days![idx - 1]?.date : undefined;
  const refresh = () => { reload(); reloadRep(); reloadMaster(); };
  if (error) return <div className="p-6 text-sm text-bad-text">{t("API nicht erreichbar: {e}. Läuft das Backend (uvicorn backend.main:app)?", { e: error })}</div>;
  if (!d || !rep) return <div className="p-6 text-sm text-slate-500">{t("lädt …")}</div>;

  const cards: any[] = d.actions.events;
  const incById = Object.fromEntries(rep.incidents.map((i: any) => [i.incident_id, i]));
  const evOf = (ids: string[]) => ids.flatMap((id) => incById[id]?.evidence_ids || []);
  const scrollTo = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "center" });
  const openEvent = (e: any) => router.push(e.letter ? `/p/${pid}/schreiben/${e.letter.letter_id}` : `/p/${pid}/schreiben/ereignis/${e.event_id}`);
  const openEvidence = (title: string, ids: string[]) => drawer.open({ title, subtitle: t("Belege"), evidence: ids, showEvidence: true });

  // ------------------------------------------------------------ B2 Heute beachten (regelbasiert, jede Zeile mit Quelle)
  type Hint = { key: string; rank: number; text: string; go: () => void };
  const hints: Hint[] = [];
  for (const e of cards) {
    const rd = e.recommended_document;
    if (!rd.requires_letter || !["open", "draft"].includes(e.status)) continue;
    hints.push({
      key: e.event_id, rank: URGENCY[e.deadline?.level] ?? 5,
      text: t("{doc} „{ev}“ {state} – {dl}", {
        doc: t(rd.label), ev: t(e.label), dl: t(e.deadline?.label || ""),
        state: e.letter ? t("noch nicht freigegeben") : t("noch nicht erstellt"),
      }),
      go: () => scrollTo(`ev-${e.event_id}`),
    });
  }
  for (const m of rep.milestones_at_risk as string[]) {
    const ids = rep.deviations.filter((x: any) => x.kind === "finish_delay").flatMap((x: any) => x.linked_incident_ids);
    hints.push({ key: m, rank: 1.5, text: t(m), go: () => openEvidence(t("Meilenstein gefährdet"), evOf(ids)) });
  }
  for (const r of rep.equipment) {
    if (r.status === "im Einsatz") continue;
    hints.push({
      key: r.name, rank: 2, text: `${t(r.name)}: ${t(r.status)} ${r.downtime.map((s: any) => span(s, t)).join(", ")}`,
      go: () => (r.event_ids?.[0] ? scrollTo(`ev-${r.event_ids[0]}`) : openEvidence(t(r.name), r.evidence_ids)),
    });
  }
  for (const w of rep.workforce) {
    if (w.count === null || w.count >= w.planned) continue;
    hints.push({ key: w.crew, rank: 3, text: t("{c}: {n} von {p} Personen", { c: t(w.crew), n: w.count, p: w.planned }),
      go: () => openEvidence(t(w.crew), w.evidence_ids) });
  }
  hints.sort((a, b) => a.rank - b.rank);

  // ------------------------------------------------------------ Personal-Summen wie Bericht § 2
  const wf: any[] = rep.workforce;
  const known = wf.filter((r) => r.count !== null);
  const idleSum = wf.reduce((s, r) => s + (r.idle_hours || 0), 0);
  const m = rep.meta;

  return (
    <div className="mx-auto max-w-[1440px] space-y-4 px-4 py-4 lg:px-6">
      {/* Kopf: Projekt + Berichtstag */}
      <div className="flex flex-wrap items-center gap-2">
        <Link href={`/p/${pid}/projekt`} className="group block min-w-0" title={t("Projekt bearbeiten")}>
          <div className="flex items-center gap-1 truncate font-semibold">{d.project.title} <Pencil className="h-3.5 w-3.5 text-slate-400 group-hover:text-accent-text" /></div>
          <div className="text-2xs text-slate-600">{t("Vertrag")} {d.project.contract_no} · {d.project.client?.name}</div>
        </Link>
        <div className="ml-auto flex items-center gap-3">
          <CalendarDays className="h-9 w-9 shrink-0 text-accent-text" />
          <div>
            <div className="text-2xl font-bold leading-tight tabular-nums">{bigDate(d.date)}</div>
            <div className="text-xs text-slate-600">{t("Bautagesbericht Nr. {n}", { n: m.report_no ?? "–" })}</div>
          </div>
        </div>
        <a className="btn-xs" href={`/api/projects/${pid}/daily-report?date=${d.date}`}><FileDown className="h-3.5 w-3.5" /> PDF</a>
        <span className="md:hidden"><LangToggle /></span>
      </div>

      {/* Verlauf: früherer Berichtstag */}
      {day && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-accent bg-accent-soft px-3 py-2 text-sm text-accent-text">
          <History className="h-4 w-4" /> <span className="font-medium">{t("Verlauf – Bericht vom {d}", { d: dLong(d.date) })}</span>
          <span className="ml-auto flex flex-wrap gap-1.5">
            {older && <Link className="btn-xs" href={`/p/${pid}/verlauf/${older}`}><ChevronLeft className="h-3.5 w-3.5" /> {dShort(older)}</Link>}
            {newer && <Link className="btn-xs" href={`/p/${pid}/verlauf/${newer}`}>{dShort(newer)} <ChevronRight className="h-3.5 w-3.5" /></Link>}
            <Link className="btn-xs" href={`/p/${pid}/verlauf`}>{t("Alle Tage")}</Link>
            <Link className="btn-xs" href={`/p/${pid}`}>{t("Zu heute")}</Link>
          </span>
        </div>
      )}

      {/* B2 Heute beachten */}
      {hints.length > 0 && (
        <div className="rounded-lg border-2 border-bad bg-bad-soft/60 p-3">
          <div className="mb-1 flex items-center gap-2 text-sm font-semibold text-bad-text"><AlertCircle className="h-4 w-4" /> {t(day ? "An diesem Tag beachten" : "Heute beachten")}</div>
          <ul className="space-y-1 text-sm">
            {hints.slice(0, 5).map((h) => (
              <li key={h.key}>
                <button className="group flex items-start gap-1.5 text-left hover:underline" onClick={h.go}>
                  <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-bad" />
                  <span>{h.text}</span>
                  <ArrowRight className="mt-0.5 h-3.5 w-3.5 shrink-0 opacity-0 group-hover:opacity-100" />
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* B3 + B4 */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Section icon={Building2} title={t("Projektübersicht")}>
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-slate-600"><tr>
              <th className={th}>{t("Vorgang")}</th><th className={`${th} text-right`}>{t("Ist")}</th><th className={th}>{t("Plan → Prognose Ende")}</th>
            </tr></thead>
            <tbody>
              {rep.work_performed.map((r: any) => (
                <tr key={r.activity_id} className="row-click border-t border-slate-100" onClick={() => openEvidence(`${r.activity_id} ${t(r.description)}`, r.evidence_ids)}>
                  <td className={td}>
                    <span className="text-slate-500">{r.activity_id}</span> {t(r.description)}
                    {r.critical && <span className="ml-1 inline-block h-2 w-2 rounded-full bg-bad align-middle" title={t("kritischer Pfad")} />}
                  </td>
                  <td className={`${td} text-right tabular-nums`}>{pct((r.progress_pct ?? 0) / 100)}</td>
                  <td className={`${td} whitespace-nowrap tabular-nums`}>
                    {dShort(r.planned_finish)} → {dShort(r.forecast_finish)}
                    {r.delay_days > 0 && <span className="pill ml-1.5 bg-bad-soft text-bad-text">+{t("{n} AT", { n: r.delay_days })}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {rep.impact_chains.map((c: string) => <p key={c} className="mt-2 text-xs text-slate-600">{t(c)}</p>)}
        </Section>

        <Section icon={TrendingUp} title={t("Tagesfortschritt")}
          right={<button className="btn-xs" onClick={() => drawer.open({ title: t("Captures"), subtitle: dLong(d.date), body: <CaptureTimeline caps={rep.progress_captures} /> })}>
            <Camera className="h-3.5 w-3.5" /> {t("Captures")} ({rep.progress_captures.length})</button>}>
          <div className="space-y-2">
            {rep.work_performed.filter((r: any) => r.quantity_planned).map((r: any) => {
              const ratio = r.ratio_pct === null ? null : r.ratio_pct / 100;
              return (
                <div key={r.activity_id} role="button" tabIndex={0} className="row-click grid grid-cols-[minmax(0,10rem)_minmax(0,1fr)_auto] items-center gap-2 px-1 py-0.5 text-sm"
                  onClick={() => openEvidence(`${r.activity_id} ${t(r.description)}`, r.evidence_ids)}>
                  <span className="truncate" title={t(r.description)}>{t(r.description)}</span>
                  <Chevron ratio={ratio} />
                  <span className="whitespace-nowrap text-right text-xs tabular-nums">
                    {num(r.quantity_actual)}/{num(r.quantity_planned)} {r.unit} · <b>{pct(ratio)}</b>
                  </span>
                </div>
              );
            })}
            {d.today.extra_work.map((e: any) => (
              <div key={e.event_id} role="button" tabIndex={0} onClick={() => scrollTo(`ev-${e.event_id}`)}
                className="row-click grid grid-cols-[minmax(0,10rem)_minmax(0,1fr)_auto] items-center gap-2 px-1 py-0.5 text-sm">
                <span className="truncate text-warn-text">+ {t(e.label)}</span>
                <div className="flex h-6 items-center truncate border-2 border-dashed border-warn px-1.5 text-xs text-warn-text">
                  {e.cause} · {t(e.attrs?.not_in_lv ? "nicht im LV" : "LV prüfen")}
                </div>
                <AlertTriangle className="h-4 w-4 text-warn" />
              </div>
            ))}
          </div>
          <div className="mt-2 flex gap-3 text-2xs text-slate-600">
            <span className="inline-flex items-center gap-1"><span className="h-2.5 w-3 bg-bad" />&lt; 60 %</span>
            <span className="inline-flex items-center gap-1"><span className="h-2.5 w-3 bg-warn" />60–89 %</span>
            <span className="inline-flex items-center gap-1"><span className="h-2.5 w-3 bg-ok" />≥ 90 %</span>
            <span>· {t("Ist / Tagessoll")}</span>
          </div>
        </Section>
      </div>

      {/* B5 Witterung (§ 1) */}
      <div className="card flex flex-wrap items-center gap-x-5 gap-y-1 px-4 py-2 text-sm">
        <span className="flex items-center gap-2 font-semibold"><CloudRain className="h-[18px] w-[18px]" /> {t("Witterung")}</span>
        {rep.weather ? (
          <>
            <span>{t(rep.weather.condition)}</span>
            <span className="tabular-nums">{num(rep.weather.temp_min_c)} / {num(rep.weather.temp_max_c)} °C</span>
            <span className="tabular-nums">{t("Niederschlag")} {num(rep.weather.precipitation_mm)} mm</span>
            <span>{t(rep.weather.wind)}</span>
            <span className={rep.weather.work_possible ? "" : "font-semibold text-bad-text"}>{t("Arbeitsfähigkeit")}: {t(rep.weather.work_possible ? "gegeben" : "nicht gegeben")}</span>
            {rep.weather.impact_note && <span className="text-xs text-slate-600">{t(rep.weather.impact_note)}</span>}
            <span className="ml-auto text-2xs text-slate-500">{t("DWD · automatisch")}{rep.weather.fetched_at ? ` · ${rep.weather.fetched_at.slice(11, 16)}` : ""}</span>
          </>
        ) : <span className="text-slate-600">{t(m.has_coords === false ? "Keine Wetterdaten – Koordinaten der Baustelle in den Projekt-Stammdaten eintragen" : "Wetterdienst gerade nicht erreichbar – wird automatisch erneut versucht")}</span>}
      </div>

      {/* B6 Personaleinsatz (§ 2) */}
      <Section icon={Users} title={t("Personaleinsatz")}>
        <ReportTable pid={pid} date={d.date} section="workforce" keyField="crew" keyLabel="Firma / Kolonne" addLabel="Kolonne hinzufügen"
          rows={wf} onSaved={refresh} actions={(r) => <EvidenceBtn ids={r.evidence_ids} title={t(r.crew)} />}
          cols={[
            { key: "trade", label: "Gewerk", type: "text", show: (r) => t(r.trade || "–") },
            { key: "planned", label: "Soll", type: "int", right: true },
            { key: "count", label: "Ist", type: "int", right: true,
              show: (r) => <span className={r.count !== null && r.count < r.planned ? "font-semibold text-bad-text" : ""}>{r.count === null ? "–" : `${r.count}${r.derived ? " *" : ""}`}</span> },
            { key: "hours_total", label: "Stunden", type: "num", right: true },
            { key: "idle_hours", label: "davon Stillstand", type: "num", right: true, show: (r) => (r.idle_hours ? `${num(r.idle_hours)} h` : "–") },
          ]}
          footer={
            <tr className="border-t-2 border-slate-800 font-semibold">
              <td className={td}>{t("Summe")}</td><td className={td} />
              <td className={`${td} text-right tabular-nums`}>{wf.reduce((s, r) => s + (r.planned || 0), 0)}</td>
              <td className={`${td} text-right tabular-nums`}>{known.length ? known.reduce((s, r) => s + r.count, 0) : "–"}</td>
              <td className={`${td} text-right tabular-nums`}>{num(wf.reduce((s, r) => s + (r.hours_total || 0), 0))}</td>
              <td className={`${td} text-right tabular-nums`}>{idleSum ? `${num(idleSum)} h` : "–"}</td><td className={td} />
            </tr>
          } />
        {wf.some((r) => r.derived) && <p className="mt-1 text-2xs text-slate-600">{t("* nicht einzeln erfasst – aus der gemeldeten Gesamtzahl abgeleitet.")}</p>}
      </Section>

      {/* B7 Geräteeinsatz (§ 3) */}
      <Section icon={Wrench} title={t("Geräteeinsatz")}>
        {!rep.equipment.length && <p className="mb-2 text-sm text-slate-600">{t("Kein Großgerät im Tagesverlauf erfasst.")}</p>}
        <ReportTable pid={pid} date={d.date} section="equipment" keyField="name" keyLabel="Gerät" addLabel="Gerät hinzufügen"
          rows={rep.equipment} onSaved={refresh} actions={(r) => <EvidenceBtn ids={r.evidence_ids} title={t(r.name)} />}
          cols={[
            { key: "status", label: "Status", type: "select", options: ["im Einsatz", "Stillstand", "Ausfall", "nicht eingesetzt"],
              show: (r) => <span className={r.status !== "im Einsatz" ? "font-semibold text-bad-text" : ""}>{t(r.status)}</span> },
            { key: "hours_planned", label: "Soll h", type: "num", right: true },
            { key: "hours_operated", label: "Ist h", type: "num", right: true },
            { key: "downtime", label: "Ausfallzeit", type: "spans",
              show: (r) => <span className="whitespace-nowrap tabular-nums">{r.downtime?.length ? r.downtime.map((s: any) => span(s, t)).join(", ") : "–"}</span> },
            { key: "downtime_cause", label: "Ursache", type: "text", show: (r) => <span className="text-xs">{r.downtime_cause || "–"}</span> },
            { key: "remarks", label: "Bemerkung", type: "text",
              show: (r) => <span className="text-xs">{r.unplanned && <span className="pill mr-1 bg-warn-soft text-warn-text">{t("nicht im Einsatzplan")}</span>}{r.remarks ? t(r.remarks.replace(/^nicht im Einsatzplan;? ?/, "")) : (r.unplanned ? "" : "–")}</span> },
          ]} />
      </Section>

      {/* B8 Lieferungen (§ 4) */}
      <Section icon={Truck} title={t("Lieferungen")}>
        {rep.deliveries.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-slate-600"><tr>
                <th className={th}>{t("Lieferant")}</th><th className={th}>{t("Material")}</th><th className={`${th} text-right`}>{t("Menge")}</th>
                <th className={th}>{t("geplant")}</th><th className={th}>{t("tatsächlich")}</th><th className={th}>{t("pünktlich")}</th>
                <th className={th}>{t("Status")}</th><th className={`${th} text-right`}>{t("bisher gesamt")}</th>
                <th className={th}>{t("Lieferschein")}</th><th className={`${th} text-right`}>{t("Belege")}</th>
              </tr></thead>
              <tbody>
                {rep.deliveries.map((r: any, i: number) => (
                  <tr key={i} className="border-t border-slate-100">
                    <td className={td}>{r.supplier || "–"}</td><td className={td}>{r.material}</td>
                    <td className={`${td} text-right tabular-nums`}>{r.quantity != null ? `${num(r.quantity)} ${r.unit}` : "–"}</td>
                    <td className={td}>{r.planned_time || "–"}</td><td className={td}>{r.actual_time || "–"}</td>
                    <td className={td}>{!r.actual_time ? "–" : r.delay_minutes ? t("{n} min Verzug", { n: r.delay_minutes }) : r.planned_time ? t("ja") : "–"}</td>
                    <td className={td}>
                      <span className={r.status === "geliefert" ? "" : "font-semibold text-bad-text"}>{t(r.status?.startsWith("überfällig") ? "überfällig" : r.status || "geliefert")}</span>
                      {r.announced_on && <span className="block text-2xs text-slate-500">{t("angekündigt am {d}", { d: dShort(r.announced_on) })}</span>}
                      {r.previous_delivery && <span className="block text-2xs text-slate-500">{t("zuletzt {d}", { d: dShort(r.previous_delivery) })}</span>}
                    </td>
                    <td className={`${td} text-right tabular-nums`}>{r.total_to_date != null ? `${num(r.total_to_date)} ${r.unit}` : "–"}</td>
                    <td className={td}>{r.delivery_note_no || "–"}</td>
                    <td className={`${td} text-right`}><EvidenceBtn ids={r.evidence_ids || []} title={r.material} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <p className="text-sm text-slate-600">{t("Keine Lieferungen erfasst.")}</p>}
      </Section>

      {/* Tagesbuch: Prüfungen, Besuche, Geräte-Befunde, erledigte Arbeiten (kein Ereignis, kein Regelwerk) */}
      {(rep.site_log || []).length > 0 && (
        <Section icon={NotebookPen} title={t("Prüfungen, Besuche und weitere Feststellungen")}>
          <ul className="divide-y divide-slate-100 text-sm">
            {rep.site_log.map((r: any) => (
              <li key={r.log_id} className="flex items-start gap-3 py-2">
                <span className="w-12 shrink-0 font-mono text-xs text-slate-500">{r.time || "–"}</span>
                <span className="pill shrink-0 bg-slate-100 text-slate-700">{t(r.label)}</span>
                <div className="min-w-0 flex-1">
                  <div>{r.text}</div>
                  {r.detail && <div className="text-xs text-slate-600">{t(r.detail)}</div>}
                </div>
                <EvidenceBtn ids={r.evidence_ids || []} title={t(r.label)} />
              </li>
            ))}
          </ul>
        </Section>
      )}

      {/* B9 Handlungsbedarf (§ 7) */}
      <section>
        <div className="section-head">
          <h2 className="flex items-center gap-2 font-semibold"><HardHat className="h-[18px] w-[18px]" /> {t("Handlungsbedarf")}</h2>
          <span className={`pill ${d.actions.pending_letters ? "bg-bad-soft text-bad-text" : "bg-ok-soft text-ok-text"}`}>{t("{n} Schreiben offen", { n: d.actions.pending_letters })}</span>
        </div>
        <div className="grid gap-2">
          {cards.map((e) => (
            <div key={e.event_id} id={`ev-${e.event_id}`} className="scroll-mt-4 rounded-lg target:ring-2">
              {e.carried_from && <div className="mb-0.5 text-2xs font-medium text-warn-text">{t("offen seit {d}", { d: dLong(e.carried_from) })}</div>}
              <EventCard e={e} pid={pid} onOpen={() => openEvent(e)} onChanged={refresh} />
            </div>
          ))}
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <a className="btn" href={`/api/projects/${pid}/daily-report?date=${d.date}`}><FileDown className="h-[18px] w-[18px]" /> {t("Bautagesbericht exportieren")}</a>
          <Link className="btn" href={`/p/${pid}/schreiben`}><ListChecks className="h-[18px] w-[18px]" /> {t("Review-Queue öffnen")} <ArrowRight className="h-3.5 w-3.5" /></Link>
        </div>
      </section>
    </div>
  );
}
