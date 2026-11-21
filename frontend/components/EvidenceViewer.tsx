"use client";
import { useEffect, useRef, useState } from "react";
import { FileText, Image as ImageIcon, Mail, Mic, Calculator, CloudRain, BookOpen, StickyNote, Eye } from "lucide-react";
import { locale, useT } from "@/lib/i18n";
import { post, time, useApi } from "@/lib/api";

export const SOURCE_ICON: Record<string, any> = {
  audio: Mic, photo: ImageIcon, email: Mail, note: StickyNote, document: FileText, contract: BookOpen, engine: Calculator, weather: CloudRain,
  ai_vision: Eye,
};
const SOURCE_LABEL: Record<string, string> = {
  audio: "Sprachmemo", photo: "Foto", email: "E-Mail", note: "Notiz", document: "Dokument", contract: "Vertrag / LV",
  engine: "Berechnung (Engine)", weather: "Wetter (DWD)", ai_vision: "KI-Beobachtung",
};
export const AI_STATUS: Record<string, { label: string; cls: string }> = {
  ai: { label: "KI-Beobachtung – kein Beleg", cls: "bg-warn-soft text-warn-text" },
  corroborated: { label: "durch Antwort gestützt", cls: "bg-ok-soft text-ok-text" },
  confirmed: { label: "von Bauleitung bestätigt", cls: "bg-ok-soft text-ok-text" },
  rejected: { label: "verworfen", cls: "bg-slate-200 text-slate-600" },
};

/** KI-Beobachtung aus einem Foto: Hinweis, kein Beleg. Bestätigen macht sie zum Beleg (Audit-Log). */
function AiObservation({ ev, onChange }: { ev: any; onChange?: () => void }) {
  const { t } = useT();
  const m = ev.meta || {};
  const st = AI_STATUS[m.status] || AI_STATUS.ai;
  const { data: crop } = useApi<any>(m.crop_evidence_id ? `/api/evidence/${m.crop_evidence_id}` : null);
  const review = async (action: string) => {
    await post(`/api/evidence/${ev.evidence_id}/review`, { action });
    onChange?.();
  };
  return (
    <div className="space-y-1 text-sm">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className={`pill ${st.cls}`}>{t(st.label)}</span>
        {m.visual_conf != null && <span className="text-2xs text-slate-600">{t("visuelle Sicherheit {c}", { c: Number(m.visual_conf).toFixed(2) })}</span>}
        {m.model && <span className="text-2xs text-slate-500">{m.model}</span>}
      </div>
      {crop?.file && <img src={`/files/${crop.file}`} alt={ev.title} className="max-h-40 rounded border" />}
      <p className="italic text-slate-700">{ev.quote}</p>
      <div className="flex gap-1">
        {m.status !== "confirmed" && m.status !== "rejected" && <button className="btn-xs" onClick={() => review("confirm")}>{t("bestätigen")}</button>}
        {m.status !== "rejected" && <button className="btn-xs" onClick={() => review("reject")}>{t("verwerfen")}</button>}
        {(m.status === "confirmed" || m.status === "rejected") && <button className="btn-xs" onClick={() => review("reset")}>{t("zurücksetzen")}</button>}
      </div>
    </div>
  );
}

function clock(capturedAt: string | undefined, offset: number | null | undefined) {
  if (!capturedAt || offset === null || offset === undefined) return "";
  const d = new Date(capturedAt);
  d.setMilliseconds(d.getMilliseconds() + offset * 1000);
  return d.toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/** Audio spielt ab t_start; Wörter mit niedrigem ASR-Score sind unterstrichen. */
function AudioEvidence({ ev }: { ev: any }) {
  const { t } = useT();
  const ref = useRef<HTMLAudioElement>(null);
  const words = (ev.transcript?.segments || []).flatMap((s: any) => s.words);
  useEffect(() => {
    if (ref.current && ev.t_start != null) ref.current.currentTime = ev.t_start;
  }, [ev.t_start]);
  const play = () => {
    if (!ref.current) return;
    ref.current.currentTime = ev.t_start || 0;
    ref.current.play().catch(() => {});
  };
  return (
    <div className="space-y-2">
      {ev.file && <audio ref={ref} controls preload="metadata" src={`/files/${ev.file}#t=${ev.t_start ?? 0}`} className="h-8 w-full" />}
      <div className="flex flex-wrap items-center gap-2 text-2xs text-slate-600">
        <button className="btn-xs" onClick={play}>▶ {t("ab {t}", { t: clock(ev.captured_at, ev.t_start) || "Start" })}</button>
        {ev.t_start != null && <span>{t("Abschnitt {a}–{b} s", { a: ev.t_start.toFixed(1), b: ev.t_end?.toFixed(1) })}</span>}
        {ev.asr_score != null && <span>{t("ASR-Score {s}", { s: ev.asr_score.toFixed(2) })}</span>}
      </div>
      {words.length > 0 && (
        <p className="text-sm leading-relaxed">
          {words.map((w: any, i: number) => {
            const inSpan = ev.t_start != null && w.start >= ev.t_start - 0.01 && w.end <= (ev.t_end ?? 0) + 0.01;
            const low = w.score != null && w.score < 0.7;
            return (
              <span key={i} title={w.score != null ? `Score ${w.score}` : undefined}
                className={`${inSpan ? "bg-yellow-100" : "text-slate-600"} ${low ? "underline decoration-bad decoration-wavy" : ""}`}>
                {w.word}{" "}
              </span>
            );
          })}
        </p>
      )}
    </div>
  );
}

export function EvidenceBody({ ev, onChange }: { ev: any; onChange?: () => void }) {
  const { t } = useT();
  if (ev.source === "audio") return <AudioEvidence ev={ev} />;
  if (ev.source === "ai_vision") return <AiObservation ev={ev} onChange={onChange} />;
  if (ev.source === "photo")
    return (
      <div className="space-y-1">
        {ev.file && <img src={`/files/${ev.file}`} alt={ev.title} className="w-full rounded border" />}
        {ev.quote && <p className="text-sm">{ev.quote}</p>}
        <p className="text-2xs text-slate-600">
          {{ crop: t("Ausschnitt aus dem Originalfoto"), detail: t("Detailfoto"), original: t("Originalfoto") }[ev.meta?.role as string] || t("Foto")}
          {ev.meta?.gps ? ` · GPS ${ev.meta.gps.lat}, ${ev.meta.gps.lon}` : ""}
        </p>
      </div>
    );
  if (ev.source === "email")
    return (
      <div className="space-y-1 text-sm">
        {ev.email && <p className="text-2xs text-slate-600">{t("Von {f} · {s}", { f: ev.email.from, s: ev.email.subject })}</p>}
        <blockquote className="border-l-2 border-accent pl-2 italic">„{ev.quote}“</blockquote>
        <details className="text-xs text-slate-600"><summary className="cursor-pointer">{t("Originaltext")}</summary><pre className="mt-1 whitespace-pre-wrap font-sans">{ev.full_text}</pre></details>
      </div>
    );
  return (
    <div className="space-y-1 text-sm">
      <blockquote className="whitespace-pre-wrap border-l-2 border-slate-300 pl-2">{ev.quote}</blockquote>
      {ev.page && <p className="text-2xs text-slate-600">{t("Seite {n}", { n: ev.page })}{ev.meta?.relevance != null ? ` · ${t("Retrieval-Relevanz {r}", { r: Number(ev.meta.relevance).toFixed(2) })}` : ""}</p>}
      {ev.source === "engine" && ev.full_text && ev.full_text !== ev.quote && <pre className="whitespace-pre-wrap font-sans text-xs text-slate-600">{ev.full_text}</pre>}
    </div>
  );
}

// ============================================================================ Belege nach Quelle
// Eine Sprachnachricht / ein Foto / eine Mail / ein Dokument erscheint nur einmal; alle Fundstellen darin
// werden hervorgehoben, die ausgewählte stark (und dorthin gescrollt bzw. gesprungen).

type Group = { key: string; source: string; title?: string; captured_at?: string; file?: string; transcript?: any;
  full_text?: string; email?: any; gps?: any; items: any[] };

const reEsc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Zitat im Text finden – exakt oder mit abweichenden Leerzeichen/Zeilenumbrüchen → [Start, Länge]. */
function findQuote(text: string, q: string): [number, number] | null {
  const a = text.toLowerCase().indexOf(q.toLowerCase());
  if (a >= 0) return [a, q.length];
  const words = q.split(/\s+/).filter(Boolean);
  if (!words.length) return null;
  const m = new RegExp(words.map(reEsc).join("\\s+"), "i").exec(text);
  return m ? [m.index, m[0].length] : null;
}

/** Fundstellen (Zitate) im Text finden → Abschnitte mit Markierung; nicht gefundene Zitate separat. */
function markText(text: string, items: any[]) {
  const hits: { a: number; b: number; id: string }[] = [];
  const missing: any[] = [];
  for (const it of items) {
    const q = (it.quote || "").trim();
    if (!q) continue;
    const f = findQuote(text, q);
    if (!f || hits.some((h) => f[0] < h.b && f[0] + f[1] > h.a)) { missing.push(it); continue; }
    hits.push({ a: f[0], b: f[0] + f[1], id: it.evidence_id });
  }
  hits.sort((x, y) => x.a - y.a);
  const parts: { text: string; id?: string }[] = [];
  let i = 0;
  for (const h of hits) {
    if (h.a > i) parts.push({ text: text.slice(i, h.a) });
    parts.push({ text: text.slice(h.a, h.b), id: h.id });
    i = h.b;
  }
  if (i < text.length) parts.push({ text: text.slice(i) });
  return { parts, missing };
}

function Marked({ text, items, active, refs }: { text: string; items: any[]; active: string[]; refs: Record<string, string> }) {
  const { parts, missing } = markText(text, items);
  const ref = useRef<HTMLElement>(null);
  useEffect(() => { ref.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, [active.join()]);
  return (
    <div className="space-y-2">
      <div className="max-h-72 overflow-y-auto whitespace-pre-wrap rounded bg-slate-50 p-2 text-sm leading-relaxed">
        {parts.map((p, i) => p.id ? (
          <mark key={i} ref={active.includes(p.id) ? (ref as any) : undefined} title={refs[p.id]}
            className={`rounded px-0.5 ${active.includes(p.id) ? "bg-yellow-300 ring-2 ring-yellow-400" : "bg-yellow-100"}`}>{p.text}</mark>
        ) : <span key={i} className="text-slate-700">{p.text}</span>)}
      </div>
      {missing.map((m) => (
        <blockquote key={m.evidence_id} className={`border-l-2 pl-2 text-sm ${active.includes(m.evidence_id) ? "border-yellow-400 bg-yellow-100" : "border-slate-300"}`}>
          {refs[m.evidence_id] && <span className="pill mr-1 bg-slate-200 text-slate-700">{refs[m.evidence_id]}</span>}{m.quote}
        </blockquote>
      ))}
    </div>
  );
}

function AudioSource({ g, active }: { g: Group; active: string[] }) {
  const { t } = useT();
  const audio = useRef<HTMLAudioElement>(null);
  const word = useRef<HTMLSpanElement>(null);
  const words = (g.transcript?.segments || []).flatMap((s: any) => s.words);
  const spans = g.items.filter((i) => i.t_start != null);
  const act = spans.find((i) => active.includes(i.evidence_id));
  const inSpan = (w: any, i: any) => w.start >= i.t_start - 0.01 && w.end <= (i.t_end ?? i.t_start) + 0.01;
  useEffect(() => {
    if (act && audio.current) audio.current.currentTime = act.t_start;
    word.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [act?.evidence_id]);
  const play = (i: any) => { if (audio.current) { audio.current.currentTime = i.t_start || 0; audio.current.play().catch(() => {}); } };
  let firstActive = true;
  return (
    <div className="space-y-2">
      {g.file && <audio ref={audio} controls preload="metadata" src={`/files/${g.file}`} className="h-8 w-full" />}
      <div className="flex flex-wrap gap-1.5 text-2xs text-slate-600">
        {spans.map((i) => (
          <button key={i.evidence_id} className={`btn-xs ${active.includes(i.evidence_id) ? "bg-yellow-200" : ""}`} onClick={() => play(i)}>
            ▶ {t("ab {t}", { t: clock(g.captured_at, i.t_start) || `${i.t_start.toFixed(1)} s` })}
            {i.asr_score != null && <span className="text-slate-500">· ASR {i.asr_score.toFixed(2)}</span>}
          </button>
        ))}
      </div>
      {words.length > 0 ? (
        <p className="max-h-60 overflow-y-auto text-sm leading-relaxed">
          {words.map((w: any, k: number) => {
            const strong = act && inSpan(w, act);
            const weak = !strong && spans.some((i) => inSpan(w, i));
            const low = w.score != null && w.score < 0.7;
            const r = strong && firstActive ? word : undefined;
            if (strong) firstActive = false;
            return (
              <span key={k} ref={r} title={w.score != null ? `Score ${w.score}` : undefined}
                className={`${strong ? "rounded bg-yellow-300" : weak ? "bg-yellow-100" : "text-slate-600"} ${low ? "underline decoration-bad decoration-wavy" : ""}`}>
                {w.word}{" "}
              </span>
            );
          })}
        </p>
      ) : g.items.map((i) => <blockquote key={i.evidence_id} className="border-l-2 border-slate-300 pl-2 text-sm">{i.quote}</blockquote>)}
    </div>
  );
}

function PhotoSource({ g, active, refs, onChange }: { g: Group; active: string[]; refs: Record<string, string>; onChange?: () => void }) {
  const { t } = useT();
  const boxes = g.items.filter((i) => Array.isArray(i.meta?.bbox) && i.meta.bbox.length === 4);
  const ai = g.items.filter((i) => i.source === "ai_vision");
  return (
    <div className="space-y-2">
      {g.file && (
        <div className="relative">
          <img src={`/files/${g.file}`} alt={g.title} className="w-full rounded border" />
          {boxes.map((i, k) => {
            const [x1, y1, x2, y2] = i.meta.bbox;
            const on = active.includes(i.evidence_id);
            return (
              <div key={i.evidence_id} title={refs[i.evidence_id] || i.title}
                style={{ left: `${x1 / 10}%`, top: `${y1 / 10}%`, width: `${(x2 - x1) / 10}%`, height: `${(y2 - y1) / 10}%` }}
                className={`pointer-events-none absolute rounded ${on ? "border-[3px] border-yellow-400 bg-yellow-300/20" : "border-2 border-dashed border-white/80"}`}>
                <span className={`absolute -top-5 left-0 rounded px-1 text-2xs font-semibold ${on ? "bg-yellow-400 text-slate-900" : "bg-slate-900/70 text-white"}`}>{refs[i.evidence_id] || k + 1}</span>
              </div>
            );
          })}
        </div>
      )}
      <p className="text-2xs text-slate-600">{t("Originalfoto")}{g.gps ? ` · GPS ${g.gps.lat}, ${g.gps.lon}` : ""}</p>
      {ai.map((i) => (
        <div key={i.evidence_id} className={`rounded p-2 ${active.includes(i.evidence_id) ? "bg-yellow-50 ring-2 ring-yellow-300" : "bg-slate-50"}`}>
          <AiObservation ev={i} onChange={onChange} />
        </div>
      ))}
    </div>
  );
}

function SourceBody({ g, active, refs, onChange }: { g: Group; active: string[]; refs: Record<string, string>; onChange?: () => void }) {
  const { t } = useT();
  if (g.source === "audio") return <AudioSource g={g} active={active} />;
  if (g.source === "photo") return <PhotoSource g={g} active={active} refs={refs} onChange={onChange} />;
  if (["email", "note", "document"].includes(g.source))
    return (
      <div className="space-y-1">
        {g.email && <p className="text-2xs text-slate-600">{t("Von {f} · {s}", { f: g.email.from, s: g.email.subject })}</p>}
        <Marked text={g.full_text || ""} items={g.items} active={active} refs={refs} />
      </div>
    );
  if (g.source === "contract") {
    const pages = new Map<string, any[]>();
    for (const i of g.items) { const k = `${i.page ?? ""}\u0000${i.full_text || ""}`; pages.set(k, [...(pages.get(k) || []), i]); }
    return (
      <div className="space-y-2">
        {[...pages.entries()].map(([k, its]) => (
          <div key={k}>
            {its[0].page && <div className="mb-1 text-2xs text-slate-500">{t("Seite {n}", { n: its[0].page })}</div>}
            {its[0].full_text ? <Marked text={its[0].full_text} items={its} active={active} refs={refs} />
              : its.map((i: any) => <blockquote key={i.evidence_id} className="border-l-2 border-slate-300 pl-2 text-sm">{i.quote}</blockquote>)}
          </div>
        ))}
      </div>
    );
  }
  return <div className="space-y-2">{g.items.map((i) => <EvidenceBody key={i.evidence_id} ev={i} onChange={onChange} />)}</div>;
}

export function SourceCard({ g, refs = {}, active = [], onSelect, onChange }:
  { g: Group; refs?: Record<string, string>; active?: string[]; onSelect?: (id: string) => void; onChange?: () => void }) {
  const { t } = useT();
  const box = useRef<HTMLDivElement>(null);
  const has = g.items.some((i) => active.includes(i.evidence_id));
  useEffect(() => { if (has) box.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, [has, active.join()]);
  const Icon = SOURCE_ICON[g.source] || FileText;
  return (
    <div ref={box} className={`card p-3 ${has ? "ring-2 ring-accent" : ""}`}>
      <div className="mb-2 flex flex-wrap items-center gap-1.5 text-xs">
        <Icon className="h-[18px] w-[18px] text-slate-600" />
        <span className="font-medium">{t(g.title || SOURCE_LABEL[g.source])}</span>
        <span className="ml-auto text-slate-500">{t(SOURCE_LABEL[g.source])}{g.captured_at ? ` · ${time(g.captured_at)}` : ""}</span>
      </div>
      {g.items.length > 1 || Object.keys(refs).length ? (
        <div className="mb-2 flex flex-wrap items-center gap-1">
          <span className="text-2xs text-slate-500">{t("{n} Fundstellen", { n: g.items.length })}:</span>
          {g.items.map((i, k) => (
            <button key={i.evidence_id} onClick={() => onSelect?.(i.evidence_id)} title={i.quote || i.title}
              className={`rounded px-1.5 text-2xs font-semibold ${active.includes(i.evidence_id) ? "bg-yellow-300 text-slate-900" : "bg-slate-200 text-slate-700 hover:bg-slate-900 hover:text-white"}`}>
              {refs[i.evidence_id] || k + 1}
            </button>
          ))}
        </div>
      ) : null}
      <SourceBody g={g} active={active} refs={refs} onChange={onChange} />
    </div>
  );
}

export function useEvidenceSources(ids: string[]) {
  const key = [...new Set(ids)].join(",");
  return useApi<Group[]>(key ? `/api/evidence-sources?ids=${encodeURIComponent(key)}` : null);
}

/** Liste der Quellen zu Beleg-IDs – jede Quelle einmal; Klick auf eine Fundstelle hebt sie hervor. */
export function EvidenceSources({ ids, refs, active: activeProp, only, onSelect }:
  { ids: string[]; refs?: Record<string, string>; active?: string[]; only?: string[]; onSelect?: (id: string) => void }) {
  const { t } = useT();
  const { data, reload } = useEvidenceSources(ids);
  const [own, setOwn] = useState<string[]>([]);
  const active = activeProp ?? own;
  if (!data) return <div className="card p-3 text-xs text-slate-500">{t("lädt …")}</div>;
  const groups = only ? data.filter((g) => g.items.some((i) => only.includes(i.evidence_id))) : data;
  return (
    <div className="space-y-2">
      {groups.map((g) => (
        <SourceCard key={g.key} g={g} refs={refs} active={active} onChange={reload}
          onSelect={(id) => { setOwn([id]); onSelect?.(id); }} />
      ))}
    </div>
  );
}
