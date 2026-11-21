"use client";
import { useEffect, useRef } from "react";
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

export function EvidenceCard({ id, refLabel, active }: { id: string; refLabel?: string; active?: boolean }) {
  const { data: ev, reload } = useApi<any>(`/api/evidence/${id}`);
  const { t } = useT();
  if (!ev) return <div className="card p-3 text-xs text-slate-500">{t("lädt {id} …", { id })}</div>;
  const Icon = SOURCE_ICON[ev.source] || FileText;
  return (
    <div className={`card p-3 ${active ? "ring-2 ring-accent" : ""}`}>
      <div className="mb-2 flex items-center gap-2 text-xs">
        <Icon className="h-[18px] w-[18px] text-slate-600" />
        {refLabel && <span className="pill bg-slate-900 text-white">{refLabel}</span>}
        <span className="font-medium">{t(ev.title || SOURCE_LABEL[ev.source])}</span>
        <span className="ml-auto text-slate-500">{t(SOURCE_LABEL[ev.source])}{ev.captured_at ? ` · ${time(ev.captured_at)}` : ""}</span>
      </div>
      <EvidenceBody ev={ev} onChange={reload} />
    </div>
  );
}
