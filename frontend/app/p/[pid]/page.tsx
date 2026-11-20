"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { AlertCircle, ArrowRight, Building2, CalendarClock, CloudRain, FileDown, ListChecks, Pencil } from "lucide-react";
import { api, dLong, dShort, num, pct, post, put, RES_STATUS, useApi } from "@/lib/api";
import { LangToggle, useT } from "@/lib/i18n";
import { useDrawer } from "@/components/Drawer";
import Gantt from "@/components/Gantt";
import { BulletRow, ExtraWorkRow } from "@/components/Bullet";
import DayTimeline from "@/components/DayTimeline";
import EventCard, { EventDetail } from "@/components/EventCard";
import { Legend, Ratio } from "@/components/ui";
import EditForm, { ACTIVITY_FIELDS, EVENT_FIELDS, predsToString } from "@/components/EditForm";
import StaffEditor from "@/components/StaffEditor";

const SECTIONS = [
  { id: "s1", label: "1 Projektübersicht" },
  { id: "s2", label: "2 Heute" },
  { id: "s3", label: "3 Handlungsbedarf" },
];

function Kpi({ label, children, onClick }: { label: string; children: React.ReactNode; onClick: () => void }) {
  return (
    <button className="kpi" onClick={onClick}>
      <div className="text-2xs text-slate-600">{label}</div>
      <div className="text-lg font-semibold leading-tight">{children}</div>
    </button>
  );
}

export default function Dashboard() {
  const { pid } = useParams<{ pid: string }>();
  const { data: d, error, reload } = useApi<any>(`/api/projects/${pid}/dashboard`, 20_000);
  const drawer = useDrawer();
  const router = useRouter();
  const { t } = useT();
  const { data: rawActs, reload: reloadActs } = useApi<any[]>(`/api/projects/${pid}/activities`);
  const { data: master, reload: reloadMaster } = useApi<any>(`/api/projects/${pid}/master`);
  const refresh = () => { reload(); reloadActs(); reloadMaster(); };
  if (error) return <div className="p-6 text-sm text-bad-text">{t("API nicht erreichbar: {e}. Läuft das Backend (uvicorn backend.main:app)?", { e: error })}</div>;
  if (!d) return <div className="p-6 text-sm text-slate-500">{t("lädt …")}</div>;
  const k = d.overview.kpis;
  const td = d.today;
  const wx = td.kpis.weather?.summary;
  const evById = Object.fromEntries(d.actions.events.map((e: any) => [e.event_id, e]));
  const evidenceOf = (ids: string[]) => ids.flatMap((id) => evById[id]?.evidence || []);
  const jump = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  const cause = (id: string) =>
    evById[id] && (
      <p key={id} className="text-xs">{t("Ursache")}: <button className="text-accent-text underline" onClick={() => openEvent(evById[id])}>{t(evById[id].label)}</button> ({evById[id].sphere})</p>
    );

  // ------------------------------------------------------------ Bearbeiten (Eingaben ändern → alles neu berechnet)
  const editEvent = (e: any) =>
    drawer.open({
      title: `${t("Ereignis bearbeiten")}: ${t(e.label)}`, subtitle: e.event_id,
      body: <EditForm fields={EVENT_FIELDS} initial={{ ...e, work_started: e.attrs?.work_started }}
        note="Risikosphäre, Empfehlung und Konfidenz werden nach dem Speichern regelbasiert neu berechnet."
        onSave={async (patch) => { await api(`/api/events/${e.event_id}`, { method: "PATCH", body: JSON.stringify(patch) }); refresh(); }}
        onDelete={async () => { await api(`/api/events/${e.event_id}`, { method: "DELETE" }); refresh(); drawer.close(); }} />,
    });
  const editActivity = (id: string) => {
    const a = rawActs?.find((x) => x.id === id);
    if (!a) return;
    drawer.open({
      title: `${t("Vorgang bearbeiten")}: ${a.name}`, subtitle: a.id,
      body: <EditForm fields={ACTIVITY_FIELDS} initial={{ ...a, preds: predsToString(a.preds), aliases: (a.aliases || []).join("; ") }}
        note="Gantt, Soll-Ist, kritischer Pfad und Prognose werden aus dem geänderten Bauzeitenplan neu berechnet."
        onSave={async (patch) => { await put(`/api/projects/${pid}/activities/${id}`, patch); refresh(); }}
        onDelete={async () => { await api(`/api/projects/${pid}/activities/${id}`, { method: "DELETE" }); refresh(); drawer.close(); }} />,
    });
  };
  const editProgress = (b: any) =>
    drawer.open({
      title: `${t("Ist-Menge korrigieren")}: ${b.name}`, subtitle: dLong(d.date),
      body: <EditForm fields={[{ key: "qty", label: `${t("Ist heute")} (${b.unit})`, type: "number", help: "Leer lassen = Eintrag löschen" }]}
        initial={{ qty: b.ist }} note="Manuelle Korrektur der aus der Sprachnotiz übernommenen Menge (Audit-Log)."
        onSave={async (patch) => { await put(`/api/projects/${pid}/progress`, { activity_id: b.id, date: d.date, qty: patch.qty }); refresh(); }} />,
    });
  const editProject = () =>
    master && drawer.open({
      title: t("Projekt-Stammdaten"), subtitle: pid,
      body: <EditForm
        note="Empfänger und Vertragsnummer neuer Schreiben werden aus diesen Stammdaten übernommen."
        fields={[
          { key: "title", label: "Bauvorhaben", type: "text" }, { key: "address", label: "Adresse Baustelle", type: "text" },
          { key: "contract_no", label: "Vertragsnummer", type: "text" }, { key: "contract_date", label: "Vertragsdatum", type: "date" },
          { key: "contract_basis", label: "Vertragsgrundlage", type: "text" },
          { key: "client.name", label: "Auftraggeber", type: "text" }, { key: "client.address", label: "Adresse AG", type: "text" },
          { key: "client.representative", label: "Bevollmächtigter Vertreter", type: "text" },
          { key: "client.representative_role", label: "Funktion", type: "text" }, { key: "client.email", label: "E-Mail AG", type: "text" },
        ]}
        initial={{ ...master, ...Object.fromEntries(Object.entries(master.client || {}).map(([k, v]) => [`client.${k}`, v])) }}
        onSave={async (patch) => {
          const body: any = { client: {} };
          for (const [k, v] of Object.entries(patch)) k.startsWith("client.") ? (body.client[k.slice(7)] = v) : (body[k] = v);
          if (!Object.keys(body.client).length) delete body.client;
          await put(`/api/projects/${pid}/master`, body);
          refresh();
        }} />,
    });

  const openEvent = (e: any) =>
    drawer.open({
      title: t(e.label), subtitle: `${e.event_id} · ${dLong(e.start)} ${e.start.slice(11, 16)}`,
      body: <div className="space-y-3"><EventDetail e={e} onChanged={reload} /><button className="btn" onClick={() => editEvent(e)}><Pencil className="h-4 w-4" /> {t("Ereignis bearbeiten")}</button></div>, evidence: e.evidence,
      edit: e.letter ? { label: "Entwurf bearbeiten", href: `/p/${pid}/schreiben/${e.letter.letter_id}` }
        : e.recommended_document.requires_letter ? { label: "Entwurf erstellen", onClick: async () => {
            const l = await post(`/api/events/${e.event_id}/draft`);
            drawer.close();
            router.push(`/p/${pid}/schreiben/${l.letter_id}`);
          } } : undefined,
    });
  const openActivity = (r: any) =>
    drawer.open({
      title: r.name, subtitle: `${r.id}${r.lv_pos ? ` · LV ${r.lv_pos}` : ""}${r.critical ? ` · ${t("kritischer Pfad")}` : ""}`,
      body: r.kind === "milestone" ? (
        <p>{t("Vertragsfrist {d}", { d: dShort(r.planned_finish) })} · {t("Prognose")} {dShort(r.forecast_finish)} {r.delay_days > 0 ? <b className="text-bad-text">(+{t("{n} AT", { n: r.delay_days })})</b> : t("(im Plan)")}</p>
      ) : (
        <div className="space-y-1 text-sm">
          <p>{t("Soll")}: {dShort(r.planned_start)}–{dShort(r.planned_finish)} · {t("Prognose")}: {dShort(r.forecast_start)}–{dShort(r.forecast_finish)}
            {r.delay_days > 0 && <b className="text-bad-text"> (+{t("{n} AT", { n: r.delay_days })})</b>}</p>
          <p>{t("Ist")} {num(r.cum)} / {num(r.qty)} {r.unit} ({pct(r.pct)}) · {t("Soll bis heute")} {pct(r.planned_pct)}</p>
          {r.today.soll > 0 && <p>{t("Heute:")} {num(r.today.ist)} {t("von")} {num(r.today.soll)} {r.unit} {t("Tagessoll")} (<Ratio r={r.today.ratio} />)</p>}
          {r.forecast_rate && <p className="text-xs text-slate-600">{t("Prognose bei aktuellem Tempo: Ø {r}/AT, Rest {x}", { r: `${num(r.forecast_rate)} ${r.unit}`, x: `${num(r.remaining)} ${r.unit}` })}</p>}
          <p className="text-xs text-slate-600">{t("Puffer (Endtermin): {n} AT", { n: r.total_float })}</p>
          {r.events.map(cause)}
        </div>
      ),
      evidence: evidenceOf(r.events), edit: { label: "Vorgang bearbeiten", onClick: () => editActivity(r.id) },
    });

  return (
    <div>
      {/* Sprungleiste – sticky im rechten Scrollbereich */}
      <div className="sticky top-0 z-20 flex items-center gap-2 border-b border-slate-200 bg-slate-50/95 px-4 py-2 backdrop-blur">
        <div className="group mr-2 min-w-0 cursor-pointer" onClick={editProject} title={t("Projekt-Stammdaten")}>
          <div className="flex items-center gap-1 truncate text-sm font-semibold">{d.project.title} <Pencil className="h-3.5 w-3.5 text-slate-400 opacity-0 group-hover:opacity-100" /></div>
          <div className="text-2xs text-slate-600">{t("Vertrag")} {d.project.contract_no} · {d.project.client?.name}</div>
        </div>
        <div className="ml-auto flex items-center gap-1">
          {SECTIONS.map((s) => <button key={s.id} className="btn-xs" onClick={() => jump(s.id)}>{t(s.label)}</button>)}
          <span className="ml-2 md:hidden"><LangToggle /></span>
        </div>
      </div>

      <div className="mx-auto max-w-5xl space-y-8 p-4">
        {d.alerts.some((a: any) => a.kind === "milestone") && (
          <div className="flex items-start gap-2 rounded-lg border border-bad/30 bg-bad-soft p-3 text-sm text-bad-text">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <div><b>{t("Auswirkung:")}</b> {t(d.overview.impact.find((c: any) => c.critical)?.text || "")}</div>
          </div>
        )}

        {/* ① Projektübersicht – gesamte Laufzeit */}
        <section id="s1" className="scroll-mt-16">
          <div className="section-head">
            <h2 className="flex items-center gap-2 font-semibold"><Building2 className="h-[18px] w-[18px]" /> {t("Projektübersicht")}</h2>
            <span className="pill bg-slate-200 text-slate-600">{t("Gesamtlaufzeit")} · KW{d.overview.window.weeks[0].kw}–{d.overview.window.weeks.at(-1).kw}</span>
          </div>
          <div className="mb-3 grid grid-cols-3 gap-2">
            <Kpi label={t("Fortschritt")} onClick={() => drawer.open({ title: t("Gesamtfortschritt"), body: <p>{t("Gewichtet nach LV-Summen. Ist {a}, Soll laut Bauzeitenplan {b}.", { a: pct(k.progress_ist, 1), b: pct(k.progress_soll, 1) })}</p> })}>
              {pct(k.progress_ist)} <span className="text-xs font-normal text-slate-600">{t("Soll")} {pct(k.progress_soll)}</span>
            </Kpi>
            <Kpi label={t("Verzug krit. Pfad")} onClick={() => drawer.open({ title: t("Verzug kritischer Pfad"), body: <div className="space-y-2">{d.overview.impact.map((c: any) => <p key={c.root} className={c.critical ? "" : "text-slate-600"}>{t(c.text)}</p>)}</div>, evidence: evidenceOf(d.overview.impact.flatMap((c: any) => c.events)) })}>
              <span className={k.critical_delay_days > 0 ? "text-bad-text" : ""}>{t("{n} AT", { n: k.critical_delay_days })}</span>
            </Kpi>
            <Kpi label={t("Nächste Vertragsfrist")} onClick={() => drawer.open({ title: t(k.next_deadline?.name || ""), body: <p>{t("Fällig am {d} – in {n} Arbeitstagen. Prognose bei aktuellem Tempo: {f}", { d: dShort(k.next_deadline?.date), n: k.next_deadline?.at_remaining, f: dShort(k.next_deadline?.forecast) })}{k.next_deadline?.overrun_days ? t(", {n} AT Überschreitung", { n: k.next_deadline.overrun_days }) : ""}.</p> })}>
              {t("{n} AT", { n: k.next_deadline?.at_remaining })} {k.next_deadline?.overrun_days > 0 && <span className="text-xs font-normal text-bad-text">{t("Prognose")} +{k.next_deadline.overrun_days}</span>}
            </Kpi>
          </div>
          <Gantt overview={d.overview} onSelect={openActivity} dense />
          <div className="pl-[144px]">
            <Legend items={[{ cls: "bg-ok", label: "Ist" }, { cls: "border border-slate-300 bg-slate-100", label: "Soll" }, { cls: "bg-bad", label: "Rückstand" },
              { cls: "border border-dashed border-bad", label: "Prognose" }, { cls: "bg-accent/70", label: "Heute" }]} />
          </div>
        </section>

        {/* ② Heute */}
        <section id="s2" className="scroll-mt-16">
          <div className="section-head">
            <h2 className="flex items-center gap-2 font-semibold"><CalendarClock className="h-[18px] w-[18px]" /> {t("Heute")}</h2>
            <span className="pill bg-accent-soft text-accent-text">{dLong(d.date)} · {t("Tagesziel")}</span>
          </div>
          <div className="mb-3 grid grid-cols-3 gap-2">
            <Kpi label={t("Tagesziel erreicht")} onClick={() => drawer.open({ title: t("Tagesziel erreicht"), body: <p>{t("Mit LV-Einheitspreisen gewichteter Anteil der heute geplanten Leistung:")} <Ratio r={td.kpis.day_target_ratio} />.</p> })}>
              <Ratio r={td.kpis.day_target_ratio} />
            </Kpi>
            <Kpi label={t("Personal")} onClick={() => drawer.open({ title: t("Personal"), body: <StaffEditor pid={pid} date={d.date} rows={td.kpis.staff.detail} onSaved={refresh} />, evidence: td.kpis.staff.detail.map((s: any) => s.evidence_id).filter(Boolean) })}>
              {td.kpis.staff.present} <span className="text-xs font-normal text-slate-600">/ {td.kpis.staff.planned}</span>
            </Kpi>
            <Kpi label={t("Wetter (DWD)")} onClick={() => drawer.open({ title: t("Wetter (DWD via Bright Sky)"), body: wx ? <div className="space-y-1"><p>{num(wx.temp_min)}–{num(wx.temp_max)} °C, {t("Niederschlag")} {num(wx.precip_sum)} mm, {t("Böen")} {num(wx.gust_max)} km/h ({wx.station}).</p><p className="text-xs">{td.kpis.weather.assessment.reasons.map((r: string) => t(r)).join("; ")}</p><p className="text-2xs text-slate-600">{t("§ 6 Abs. 2 Nr. 2 VOB/B: übliche Witterung ist keine Behinderung.")}</p></div> : <p>{t("keine Daten")}</p>, evidence: td.kpis.weather?.evidence_id ? [td.kpis.weather.evidence_id] : [] })}>
              {wx ? <span className="inline-flex items-center gap-1"><CloudRain className="h-[18px] w-[18px]" /> {num(Math.round(wx.temp_max))} °C</span> : "—"}
              {td.kpis.weather?.assessment?.exceptional === false && <span className="ml-1 text-2xs font-normal text-slate-600">{t("üblich")}</span>}
            </Kpi>
          </div>
          <div className="mb-1 text-2xs text-slate-600">{t("Tagesleistung je Vorgang · Strich = Tagessoll")}</div>
          {td.bullets.map((b: any) => (
            <BulletRow key={b.id} b={b} onClick={() => drawer.open({
              title: t("{n} heute", { n: b.name }), subtitle: b.lv_pos ? `LV ${b.lv_pos}` : undefined,
              body: <div className="space-y-1"><p>{t("Tagessoll")} {num(b.soll)} {b.unit} · {t("Ist")} {num(b.ist)} {b.unit} (<Ratio r={b.ratio} />)</p>
                <p className="text-xs text-slate-600">{t("Gesamt {a} / {b}", { a: num(b.cum), b: `${num(b.qty)} ${b.unit}` })} · {t("Prognose Ende")} {dShort(b.forecast_finish)}{b.delay_days > 0 ? ` (+${t("{n} AT", { n: b.delay_days })})` : ""}</p>
                {b.events.map(cause)}</div>,
              evidence: evidenceOf(b.events), edit: { label: "Ist-Menge korrigieren", onClick: () => editProgress(b) },
            })} />
          ))}
          {td.extra_work.map((e: any) => <ExtraWorkRow key={e.event_id} e={e} onClick={() => openEvent(e)} />)}

          <div className="mb-1 mt-5 text-2xs text-slate-600">{t("Tagesverlauf {a}–{b} Uhr · Symbole = Erfassungen", { a: td.timeline.start, b: td.timeline.end })}</div>
          <DayTimeline tl={td.timeline}
            onMarker={(m) => drawer.open({ title: t(m.title), subtitle: m.time, body: <p className="text-xs text-slate-600">{t("Verknüpft mit")}: {m.events.map((id: string) => evById[id] && t(evById[id].label)).filter(Boolean).join(", ") || "—"}</p>, evidence: [], edit: { label: "In Erfassungen öffnen", href: `/p/${pid}/erfassungen#${m.capture_id}` } })}
            onSegment={(r, s) => {
              const ev = s.event_id ? evById[s.event_id] : null;
              drawer.open({ title: `${r.name}: ${t(RES_STATUS[s.status])}`, subtitle: `${s.start}–${s.end}`,
                body: ev ? <p>{t("Ursache")}: <button className="text-accent-text underline" onClick={() => openEvent(ev)}>{t(ev.label)}</button> – {ev.cause}</p> : <p className="text-slate-600">{t("Planmäßiger Einsatz.")}</p>,
                evidence: ev?.evidence || [] });
            }} />
        </section>

        {/* ③ Handlungsbedarf */}
        <section id="s3" className="scroll-mt-16">
          <div className="section-head">
            <h2 className="flex items-center gap-2 font-semibold"><AlertCircle className="h-[18px] w-[18px]" /> {t("Handlungsbedarf")}</h2>
            <span className={`pill ${d.actions.pending_letters ? "bg-bad-soft text-bad-text" : "bg-ok-soft text-ok-text"}`}>{t("{n} Schreiben offen", { n: d.actions.pending_letters })}</span>
          </div>
          <div className="grid gap-2">
            {d.actions.events.map((e: any) => <EventCard key={e.event_id} e={e} pid={pid} onOpen={() => openEvent(e)} onChanged={reload} />)}
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <a className="btn" href={`/api/projects/${pid}/daily-report?date=${d.date}`}><FileDown className="h-[18px] w-[18px]" /> {t("Bautagesbericht exportieren")}</a>
            <Link className="btn" href={`/p/${pid}/schreiben`}><ListChecks className="h-[18px] w-[18px]" /> {t("Review-Queue öffnen")} <ArrowRight className="h-3.5 w-3.5" /></Link>
          </div>
        </section>
      </div>
    </div>
  );
}
