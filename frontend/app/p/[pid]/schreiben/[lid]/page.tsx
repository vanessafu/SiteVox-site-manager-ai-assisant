"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Fragment, useMemo, useState } from "react";
import { ArrowLeft, Check, CheckCircle2, Download, Lock, Mail, Pencil, Send, ShieldCheck, X } from "lucide-react";
import { band, dLong, post, put, useApi } from "@/lib/api";
import { EvidenceCard } from "@/components/EvidenceViewer";
import { BandDot, ConfidencePill, Disclaimer, Elapsed, SphereChip, StatusChip } from "@/components/ui";
import { useT } from "@/lib/i18n";

type Sel = { kind: "field"; key: string } | { kind: "sentence"; section: string; idx: number } | { kind: "ref"; ref: string } | null;

const BAND_BORDER: Record<string, string> = { green: "border-l-ok", yellow: "border-l-warn", red: "border-l-bad", none: "border-l-slate-200" };

function fmtValue(f: any, t: (s: string, p?: any) => string) {
  if (Array.isArray(f.value)) return f.value.join(", ");
  if (f.key === "event_start" && typeof f.value === "string" && f.value.includes("T"))
    return `${dLong(f.value)}, ${f.value.slice(11, 16)}`;
  if (f.key === "impact_estimate_days" && f.value != null) return t("{n} Arbeitstage", { n: f.value });
  return String(f.value ?? "—");
}

/** Markiert nicht belegte Werte rot, aus anderer Quelle belegte gelb gepunktet. */
function Highlighted({ text, issues }: { text: string; issues: any[] }) {
  const marks = issues.filter((i) => ["number", "date", "time", "entity", "legal_ref"].includes(i.kind) && (i.status !== "verified" || i.found_in === "andere Quelle"));
  if (!marks.length) return <>{text}</>;
  const variants = (i: any) => {
    const v = String(i.value);
    const out = [v];
    if (i.kind === "time" && v.endsWith(":00")) out.push(v.replace(/^0/, "").replace(":00", " Uhr"));
    if (i.kind === "date") out.push(v.replace(/(\d{2})\.(\d{2})\.(\d{4})/, "$1.$2.$3"));
    return out;
  };
  const parts: { t: string; cls?: string; title?: string }[] = [];
  let rest = text;
  while (rest) {
    let best: { pos: number; len: number; i: any } | null = null;
    for (const i of marks) for (const v of variants(i)) {
      const pos = rest.indexOf(v);
      if (pos >= 0 && (!best || pos < best.pos)) best = { pos, len: v.length, i };
    }
    if (!best) { parts.push({ t: rest }); break; }
    parts.push({ t: rest.slice(0, best.pos) });
    const red = best.i.status === "unverified";
    parts.push({ t: rest.slice(best.pos, best.pos + best.len), cls: red ? "mark-red" : best.i.status === "confirmed" ? "underline decoration-ok decoration-2" : "mark-amber", title: best.i.message || best.i.found_in });
    rest = rest.slice(best.pos + best.len);
  }
  return <>{parts.map((p, k) => p.cls ? <span key={k} className={p.cls} title={p.title}>{p.t}</span> : <Fragment key={k}>{p.t}</Fragment>)}</>;
}

export default function ReviewEditor() {
  const { pid, lid } = useParams<{ pid: string; lid: string }>();
  const { data: L, setData, error } = useApi<any>(`/api/letters/${lid}`);
  const [sel, setSel] = useState<Sel>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [draftText, setDraftText] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [sentMethod, setSentMethod] = useState("E-Mail vorab + Einschreiben mit Rückschein");
  const { t } = useT();

  const act = async (fn: () => Promise<any>) => {
    setMsg(null);
    try { setData(await fn()); } catch (e: any) { setMsg(e.detail?.blockers ? e.detail.blockers.map((b: string) => t(b)).join(" · ") : e.message); }
  };
  const selEvidence: string[] = useMemo(() => {
    if (!L || !sel) return [];
    if (sel.kind === "ref") return [sel.ref];
    if (sel.kind === "field") return L.fields.find((f: any) => f.key === sel.key)?.evidence_refs || [];
    const s = L.rendered.find((r: any) => r.key === sel.section)?.sentences?.[sel.idx];
    return s?.evidence || [];
  }, [L, sel]);
  if (error) return <div className="p-6 text-bad-text">{error}</div>;
  if (!L) return <div className="p-6 text-slate-500">{t("lädt …")}</div>;
  const refToId: Record<string, string> = Object.fromEntries(L.evidence.map((e: any) => [e.ref, e.evidence_id]));
  const locked = L.status !== "Entwurf";
  const issuesFor = (section: string, idx: number) => L.issues.filter((i: any) => i.section === section && i.sentence === idx);
  const red = L.issues.filter((i: any) => i.status === "unverified");

  return (
    <div className="flex h-full flex-col">
      {/* Kopf + Review-Queue */}
      <div className="sticky top-0 z-20 border-b border-slate-200 bg-white">
        <div className="flex flex-wrap items-center gap-2 px-4 py-2">
          <Link href={`/p/${pid}/schreiben`} className="rounded p-1 hover:bg-slate-100"><ArrowLeft className="h-[18px] w-[18px]" /></Link>
          <div className="min-w-0">
            <div className="flex items-center gap-2 font-semibold">{t(L.kind_label)} <StatusChip status={L.status} /></div>
            <div className="text-2xs text-slate-600">{L.letter_id} · {t(L.event?.label || "")} · {L.event && <Elapsed from={L.event.detected_at} level={L.event.deadline.level} label={L.event.deadline.label} />}</div>
          </div>
          <div className="ml-auto flex items-center gap-2">
            {L.status === "Entwurf" && (
              <button className="btn-primary" disabled={L.blockers.length > 0} title={L.blockers.map((b: string) => t(b)).join("\n")}
                onClick={() => act(() => post(`/api/letters/${lid}/release`))}>
                {L.blockers.length ? <Lock className="h-[18px] w-[18px]" /> : <ShieldCheck className="h-[18px] w-[18px]" />} {t("Freigeben")}
              </button>
            )}
            {L.status === "Entwurf" && <button className="btn" onClick={() => act(() => post(`/api/letters/${lid}/reject`, { note: "" }))}><X className="h-[18px] w-[18px]" /> {t("Verwerfen")}</button>}
          </div>
        </div>
        {L.queue.some((q: any) => q.band !== "green") && !locked && (
          <div className="flex items-center gap-1.5 overflow-x-auto px-4 pb-2 text-2xs">
            <span className="shrink-0 text-slate-600">{t("Review-Queue (unsicherste zuerst):")}</span>
            {L.queue.filter((q: any) => q.band !== "green").map((q: any) => (
              <button key={q.type + q.id} onClick={() => setSel(q.type === "field" ? { kind: "field", key: q.id } : { kind: "sentence", section: q.section, idx: q.sentence })}
                className={`pill shrink-0 border ${q.band === "red" ? "border-bad bg-bad-soft text-bad-text" : q.band === "yellow" ? "border-warn bg-warn-soft text-warn-text" : "border-slate-200 bg-white text-slate-600"}`}>
                <BandDot b={q.band} /> {t(q.label)}
              </button>
            ))}
          </div>
        )}
        {msg && <div className="bg-bad-soft px-4 py-1.5 text-xs text-bad-text">{msg}</div>}
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
        {/* Links: Entwurf */}
        <div className="space-y-4 overflow-y-auto border-r border-slate-200 p-4">
          <div className="card divide-y divide-slate-100">
            <div className="px-3 py-2 text-2xs uppercase tracking-wide text-slate-500">{t("Felder · Farbe = Konfidenz")} · <span className="normal-case">{t("Schreibentext bleibt deutsch (an deutschen AG nach VOB/B).")}</span></div>
            {L.fields.map((f: any) => {
              const isSel = sel?.kind === "field" && sel.key === f.key;
              return (
                <div key={f.key} onClick={() => setSel({ kind: "field", key: f.key })}
                  className={`cursor-pointer border-l-4 px-3 py-2 ${BAND_BORDER[f.status === "edited" || f.status === "accepted" ? "green" : f.band]} ${isSel ? "bg-accent-soft/40" : "hover:bg-slate-50"}`}>
                  <div className="flex items-center gap-2">
                    <span className="w-44 shrink-0 text-xs text-slate-600">{t(f.label)}</span>
                    {editing === `f:${f.key}` ? (
                      <input autoFocus className="flex-1 rounded border px-2 py-0.5 text-sm" value={draftText} onChange={(e) => setDraftText(e.target.value)}
                        onKeyDown={(e) => { if (e.key === "Enter") { act(() => post(`/api/letters/${lid}/fields/${f.key}`, { action: "edit", value: f.key === "impact_estimate_days" ? Number(draftText) : f.key === "affected_activities" ? draftText.split(",").map((s) => s.trim()) : draftText })); setEditing(null); } }} />
                    ) : (
                      <span className={`flex-1 text-sm ${f.status === "rejected" ? "line-through opacity-50" : ""}`}>{f.key === "sphere" ? <SphereChip sphere={f.value} /> : fmtValue(f, t)}</span>
                    )}
                    <ConfidencePill value={f.confidence} />
                  </div>
                  {f.note && <div className="ml-44 pl-2 text-2xs text-slate-500">{t(f.note)}</div>}
                  {!locked && (
                    <div className="ml-44 mt-1 flex gap-1 pl-2" onClick={(e) => e.stopPropagation()}>
                      <button className={`btn-xs ${f.status === "accepted" ? "bg-ok-soft" : ""}`} onClick={() => act(() => post(`/api/letters/${lid}/fields/${f.key}`, { action: "accept" }))}><Check className="h-3.5 w-3.5" /> {t("Übernehmen")}</button>
                      <button className={`btn-xs ${f.status === "edited" ? "bg-accent-soft" : ""}`} onClick={() => { setEditing(`f:${f.key}`); setDraftText(Array.isArray(f.value) ? f.value.join(", ") : String(f.value ?? "")); }}><Pencil className="h-3.5 w-3.5" /> {t("Bearbeiten")}</button>
                      <button className={`btn-xs ${f.status === "rejected" ? "bg-bad-soft" : ""}`} onClick={() => act(() => post(`/api/letters/${lid}/fields/${f.key}`, { action: "reject" }))}><X className="h-3.5 w-3.5" /> {t("Verwerfen")}</button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* Brief */}
          <article className="card space-y-3 p-5 text-sm leading-relaxed">
            {L.rendered.map((s: any) => {
              if (s.key === "betreff") return <p key={s.key} className="font-semibold">{s.text}</p>;
              if (s.key === "bezug") return <p key={s.key} className="text-xs text-slate-600">{t("Bezug:")} {s.text}</p>;
              if (s.key === "gruss") return <p key={s.key} className="whitespace-pre-line">{s.text}</p>;
              if (!s.sentences) return <p key={s.key} className={s.key === "vorbehalt" ? "text-slate-700" : ""}>{s.text}<span className="ml-1 text-2xs text-slate-500">{t("[Vorlage]")}</span></p>;
              return (
                <div key={s.key}>
                  <div className="mb-1 flex items-center gap-2 font-medium">{s.title} <span className="pill bg-violet-100 text-violet-700">{t("KI-Text · jeder Satz belegt")}</span></div>
                  {s.sentences.map((x: any, i: number) => {
                    const iss = issuesFor(s.key, i);
                    const bad = iss.some((q: any) => q.status === "unverified");
                    const isSel = sel?.kind === "sentence" && sel.section === s.key && sel.idx === i;
                    const eid = `s:${s.key}:${i}`;
                    return (
                      <div key={i} onClick={() => setSel({ kind: "sentence", section: s.key, idx: i })}
                        className={`group -mx-2 cursor-pointer rounded px-2 py-0.5 ${isSel ? "bg-accent-soft/50" : "hover:bg-slate-50"} ${bad ? "border-l-2 border-bad" : ""}`}>
                        {editing === eid ? (
                          <div className="space-y-1" onClick={(e) => e.stopPropagation()}>
                            <textarea className="w-full rounded border p-2 text-sm" rows={3} value={draftText} onChange={(e) => setDraftText(e.target.value)} />
                            <div className="flex gap-1"><button className="btn-xs" onClick={() => { act(() => put(`/api/letters/${lid}/sentences/${s.key}/${i}`, { text: draftText })); setEditing(null); }}>{t("Speichern & neu prüfen")}</button>
                              <button className="btn-xs" onClick={() => setEditing(null)}>{t("Abbrechen")}</button></div>
                          </div>
                        ) : (
                          <span>
                            <Highlighted text={x.text} issues={iss} />{" "}
                            {x.evidence.map((r: string) => (
                              <button key={r} onClick={(e) => { e.stopPropagation(); setSel({ kind: "ref", ref: r }); }}
                                className={`mx-0.5 rounded px-1 text-2xs font-semibold ${refToId[r] ? "bg-slate-200 text-slate-700 hover:bg-slate-900 hover:text-white" : "bg-bad text-white"}`}>[{r}]</button>
                            ))}
                            {x.edited && <span className="ml-1 text-2xs text-accent-text">{t("bearbeitet")}</span>}
                            {!locked && <button className="ml-1 hidden text-2xs text-slate-500 hover:text-slate-900 group-hover:inline" onClick={(e) => { e.stopPropagation(); setEditing(eid); setDraftText(x.text); }}>{t("bearbeiten")}</button>}
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </article>

          {/* Faktenprüfung */}
          <div className="card p-3">
            <div className="mb-2 flex items-center gap-2 text-sm font-medium">{t("Faktenprüfung")}
              <span className={`pill ${red.length ? "bg-bad-soft text-bad-text" : "bg-ok-soft text-ok-text"}`}>{red.length ? t("{n} nicht belegt", { n: red.length }) : t("alle Werte belegt")}</span>
              <span className="text-2xs font-normal text-slate-600">{t("{n} Zahlen/Daten/Namen geprüft", { n: L.issues.length })}</span>
            </div>
            <ul className="space-y-1 text-xs">
              {L.issues.filter((i: any) => i.status !== "verified" || i.found_in === "andere Quelle").map((i: any) => (
                <li key={i.issue_id} className="flex items-center gap-2">
                  <BandDot b={i.status === "unverified" ? "red" : i.status === "confirmed" ? "green" : "yellow"} />
                  <span className="font-mono">{i.value}</span>
                  <span className="text-slate-600">{i.section} · {t("Satz {n}", { n: i.sentence + 1 })} · {i.message ? t(i.message) : t("belegt in {x}", { x: t(i.found_in) })}</span>
                  {i.status === "unverified" && !locked && (
                    <button className="btn-xs ml-auto" onClick={() => { const note = window.prompt(t("Wodurch ist der Wert belegt? (geht ins Audit-Log)")) ?? ""; if (note) act(() => post(`/api/letters/${lid}/issues/${i.issue_id}/confirm`, { note })); }}>{t("manuell bestätigen")}</button>
                  )}
                </li>
              ))}
            </ul>
          </div>

          {/* Checkliste + Freigabe */}
          <div className="card p-3">
            <div className="mb-2 text-sm font-medium">{t("Checkliste vor Freigabe")}</div>
            {Object.entries(L.checklist_labels).map(([k, label]: any) => (
              <label key={k} className="flex items-center gap-2 py-0.5 text-sm">
                <input type="checkbox" disabled={locked} checked={!!L.checklist[k]} onChange={(e) => act(() => post(`/api/letters/${lid}/checklist/${k}`, { value: e.target.checked }))} />
                {t(label)}
              </label>
            ))}
            {L.status === "Entwurf" && L.blockers.length > 0 && (
              <ul className="mt-2 space-y-0.5 text-2xs text-bad-text">{L.blockers.map((b: string) => <li key={b}>• {t(b)}</li>)}</ul>
            )}
            {L.status !== "Entwurf" && L.status !== "Verworfen" && (
              <div className="mt-3 space-y-2 rounded-md bg-slate-50 p-3 text-sm">
                <div className="flex items-center gap-1 font-medium text-ok-text"><CheckCircle2 className="h-[18px] w-[18px]" /> {t("Freigegeben von {a} am {d}", { a: L.released_by, d: dLong(L.released_at) })}</div>
                <div className="flex flex-wrap gap-2">
                  <a className="btn" href={`/api/letters/${lid}/export/docx`}><Download className="h-[18px] w-[18px]" /> DOCX</a>
                  {L.exports?.pdf ? <a className="btn" href={`/api/letters/${lid}/export/pdf`}><Download className="h-[18px] w-[18px]" /> PDF</a>
                    : <span className="btn opacity-50" title={t("LibreOffice (soffice) auf dem Server installieren")}>{t("PDF n/v")}</span>}
                  <a className="btn" href={`/api/letters/${lid}/export/eml`}><Mail className="h-[18px] w-[18px]" /> {t("Outlook-Entwurf (.eml)")}</a>
                </div>
                <p className="text-2xs text-slate-600">{t("SiteVox versendet nichts. Entwurf in Outlook öffnen, prüfen und selbst auf „Senden“ klicken.")}</p>
                {L.status === "Geprüft" && (
                  <div className="flex flex-wrap items-center gap-2">
                    <select className="rounded border px-2 py-1 text-xs" value={sentMethod} onChange={(e) => setSentMethod(e.target.value)}>
                      {["E-Mail vorab + Einschreiben mit Rückschein", "E-Mail vorab + Bote mit Empfangsbestätigung", "Übergabe gegen Unterschrift"].map((o) => <option key={o} value={o}>{t(o)}</option>)}
                    </select>
                    <button className="btn" onClick={() => act(() => post(`/api/letters/${lid}/mark-sent`, { method: sentMethod }))}><Send className="h-[18px] w-[18px]" /> {t("Habe ich versendet")}</button>
                  </div>
                )}
                {L.sent_at && <div className="text-xs text-ok-text">{t("Versendet am {d}", { d: `${dLong(L.sent_at)} ${L.sent_at.slice(11, 16)}` })}</div>}
              </div>
            )}
          </div>

          <details className="card p-3 text-xs">
            <summary className="cursor-pointer font-medium">{t("Audit-Log ({n})", { n: L.audit.length })}</summary>
            <ul className="mt-2 space-y-1">{L.audit.map((a: any) => <li key={a.id} className="text-slate-600"><span className="font-mono text-slate-500">{a.ts.slice(0, 16).replace("T", " ")}</span> {a.actor} · {a.action} {a.note && `· ${a.note}`}</li>)}</ul>
          </details>
          <Disclaimer />
        </div>

        {/* Rechts: Belege */}
        <aside className="space-y-3 overflow-y-auto bg-slate-50 p-4">
          <div className="text-2xs uppercase tracking-wide text-slate-500">{t(sel ? "Belege zur Auswahl" : "Belege – Feld, Satz oder [E-xx] anklicken")}</div>
          {sel && selEvidence.length === 0 && <div className="card p-3 text-xs text-slate-600">{t("Kein Rohbeleg für diese Stelle.")} {sel.kind === "field" ? t("Wert stammt aus Vorlage/Firmenstandard – bitte bewusst übernehmen.") : ""}</div>}
          {(sel ? selEvidence : []).map((r) => refToId[r] && <EvidenceCard key={r} id={refToId[r]} refLabel={r} active />)}
          {sel?.kind === "field" && sel.key === "legal_basis" && L.legal_refs.map((h: any) => (
            <div key={h.title} className="card p-3 text-xs"><div className="mb-1 font-medium">{h.title}</div><p className="text-slate-600">{h.text}</p><p className="mt-1 text-2xs text-slate-500">{h.doc} · {t("Normzitat nur aus Vorlage")}</p></div>
          ))}
          <div className="pt-2 text-2xs uppercase tracking-wide text-slate-500">{t("Alle Belege")}</div>
          <ul className="space-y-1">
            {L.evidence.map((e: any) => (
              <li key={e.ref}>
                <button onClick={() => setSel({ kind: "ref", ref: e.ref })} className={`flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs hover:bg-white ${sel?.kind === "ref" && sel.ref === e.ref ? "bg-white ring-1 ring-accent" : ""}`}>
                  <span className="pill bg-slate-900 text-white">{e.ref}</span><span className="truncate">{t(e.title)}</span>
                  <span className="ml-auto shrink-0 text-slate-500">{e.source}</span>
                </button>
              </li>
            ))}
          </ul>
        </aside>
      </div>
    </div>
  );
}
