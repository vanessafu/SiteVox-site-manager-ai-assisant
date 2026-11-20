"use client";
import { useEffect, useRef } from "react";
import { FileText, Image as ImageIcon, Mail, Mic, Calculator, CloudRain, BookOpen, StickyNote } from "lucide-react";
import { locale, useT } from "@/lib/i18n";
import { time, useApi } from "@/lib/api";

export const SOURCE_ICON: Record<string, any> = {
  audio: Mic, photo: ImageIcon, email: Mail, note: StickyNote, document: FileText, contract: BookOpen, engine: Calculator, weather: CloudRain,
};
const SOURCE_LABEL: Record<string, string> = {
  audio: "Sprachmemo", photo: "Foto", email: "E-Mail", note: "Notiz", document: "Dokument", contract: "Vertrag / LV",
  engine: "Berechnung (Engine)", weather: "Wetter (DWD)",
};

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

export function EvidenceBody({ ev }: { ev: any }) {
  const { t } = useT();
  if (ev.source === "audio") return <AudioEvidence ev={ev} />;
  if (ev.source === "photo")
    return (
      <div className="space-y-1">
        {ev.file && <img src={`/files/${ev.file}`} alt={ev.title} className="w-full rounded border" />}
        <p className="text-sm">{ev.quote}</p>
        {ev.meta?.gps && <p className="text-2xs text-slate-600">GPS {ev.meta.gps.lat}, {ev.meta.gps.lon} · {t("Qwen3-VL-Beschreibung")}</p>}
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
  const { data: ev } = useApi<any>(`/api/evidence/${id}`);
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
      <EvidenceBody ev={ev} />
    </div>
  );
}
