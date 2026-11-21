"use client";
import { useState } from "react";
import { ChevronDown, Mic, Plus, RotateCcw, X } from "lucide-react";
import { post, useApi } from "@/lib/api";
import { useT } from "@/lib/i18n";

type Term = { term: string; category: string; count: number; sources: string[]; in_prompt: boolean; from_audio: boolean; audio_only: boolean };
type Vocab = {
  initial_prompt: string | null; hotwords: string[]; used: number; total: number; from_audio: number; audio_only: number;
  groups: { category: string; label: string; terms: Term[] }[]; removed: string[];
};

/** Spracherkennungs-Vokabular: aus Unterlagen, Foto-Text (OCR) und Stammdaten – fließt in Whisper ein. */
export default function AsrVocabulary({ pid }: { pid: string }) {
  const { t } = useT();
  const { data, setData } = useApi<Vocab>(`/api/projects/${pid}/asr-vocabulary`);
  const [term, setTerm] = useState("");
  const [busy, setBusy] = useState(false);
  const [showPrompt, setShowPrompt] = useState(false);
  const act = async (term: string, action: "add" | "remove" | "restore") => {
    setBusy(true);
    try { setData(await post<Vocab>(`/api/projects/${pid}/asr-vocabulary`, { term, action })); } finally { setBusy(false); }
  };
  const add = async () => { if (term.trim()) { await act(term.trim(), "add"); setTerm(""); } };

  return (
    <div className="card space-y-5 p-5">
      <div className="flex items-start gap-3">
        <div className="rounded-md bg-accent-soft p-2 text-accent-text"><Mic className="h-5 w-5" /></div>
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-semibold">{t("Spracherkennungs-Vokabular")}</h2>
          <p className="mt-0.5 text-sm leading-relaxed text-slate-600">
            {t("Achsen, Bauteile, Firmen und Materialien werden automatisch aus den Projektunterlagen, dem Text auf Fotos (OCR), Sprachmemos und den Stammdaten gesammelt und der Spracherkennung (Whisper) als Vokabular mitgegeben.")}
          </p>
        </div>
        {data && (
          <div className="shrink-0 text-right text-xs text-slate-600">
            <div className="text-lg font-semibold text-slate-900">{data.used}<span className="text-sm font-normal text-slate-500"> / {data.total}</span></div>
            {t("Begriffe im Prompt")}
          </div>
        )}
      </div>

      <div className="flex gap-2">
        <input className="flex-1 rounded-md border px-3 py-2 text-sm" placeholder={t("Begriff ergänzen, z. B. Kranbahn Süd")}
          value={term} onChange={(e) => setTerm(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} />
        <button className="btn" disabled={busy || !term.trim()} onClick={add}><Plus className="h-4 w-4" /> {t("Hinzufügen")}</button>
      </div>

      {!data ? <p className="text-sm text-slate-500">…</p> : (
        <div className="space-y-4">
          {data.groups.map((g) => (
            <div key={g.category}>
              <div className="mb-2 text-2xs font-medium uppercase tracking-wide text-slate-500">{t(g.label)} · {g.terms.length}</div>
              <div className="flex flex-wrap gap-1.5">
                {g.terms.map((x) => (
                  <span key={x.term} title={`${t("Quellen")}: ${x.sources.join(", ")}${x.count ? ` · ${x.count}×` : ""}${x.in_prompt ? "" : ` · ${t("nicht im Prompt (Längengrenze)")}`}`}
                    className={`group inline-flex items-center gap-1 rounded-full border py-1 pl-3 pr-1.5 text-sm ${x.in_prompt ? "border-slate-300 bg-white" : "border-dashed border-slate-300 bg-slate-50 text-slate-500"} ${x.audio_only ? "italic" : ""}`}>
                    {x.from_audio && <Mic className={`h-3.5 w-3.5 ${x.audio_only ? "text-warn-text" : "text-accent-text"}`} />}
                    {x.term}
                    {x.count > 1 && <span className="text-2xs text-slate-400">{x.count}</span>}
                    <button disabled={busy} onClick={() => act(x.term, "remove")} aria-label={t("Entfernen")}
                      className="rounded-full p-0.5 text-slate-400 hover:bg-slate-100 hover:text-bad"><X className="h-3.5 w-3.5" /></button>
                  </span>
                ))}
              </div>
            </div>
          ))}
          {data.removed.length > 0 && (
            <div>
              <div className="mb-2 text-2xs font-medium uppercase tracking-wide text-slate-500">{t("Ausgeschlossen")}</div>
              <div className="flex flex-wrap gap-1.5">
                {data.removed.map((r) => (
                  <button key={r} disabled={busy} onClick={() => act(r, "restore")} title={t("Wiederherstellen")}
                    className="inline-flex items-center gap-1 rounded-full border border-dashed px-3 py-1 text-sm text-slate-500 line-through hover:text-slate-800 hover:no-underline">
                    {r} <RotateCcw className="h-3.5 w-3.5" />
                  </button>
                ))}
              </div>
            </div>
          )}
          <div className="space-y-1 text-xs text-slate-500">
            <p className="flex items-start gap-1.5"><Mic className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent-text" />
              {t("Auch in Sprachmemos genannt ({n} Begriffe) – Transkripte von Sprachmemos und gesprochenen Foto-Antworten werden mit ausgewertet.", { n: data.from_audio })}</p>
            {data.audio_only > 0 && <p className="flex items-start gap-1.5"><Mic className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warn-text" />
              <i>{t("Nur aus Audio ({n}): könnte selbst ein Erkennungsfehler sein, daher nachrangig und nicht als Hotword. Prüfen und ggf. entfernen.", { n: data.audio_only })}</i></p>}
            <p>{t("Gestrichelt: wegen der Prompt-Längengrenze von Whisper (~224 Token) nicht übergeben. Entfernen Sie unwichtige Begriffe, damit wichtigere nachrücken.")}</p>
          </div>
          <div className="border-t pt-3">
            <button className="flex items-center gap-1 text-sm text-slate-600 hover:text-slate-900" onClick={() => setShowPrompt((s) => !s)}>
              <ChevronDown className={`h-4 w-4 transition-transform ${showPrompt ? "rotate-180" : ""}`} /> {t("Prompt-Vorschau (an Whisper übergeben)")}
            </button>
            {showPrompt && (
              <div className="mt-2 space-y-2 rounded-md bg-slate-50 p-3 text-xs leading-relaxed">
                <div><b>initial_prompt</b> ({(data.initial_prompt || "").length} {t("Zeichen")}): {data.initial_prompt}</div>
                <div><b>hotwords</b>: {data.hotwords.join(" · ")}</div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
