"use client";
import { useT } from "@/lib/i18n";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Camera, Check, Loader2, Mic, Monitor, PencilLine, Send, SkipForward, Square, Trash2, X } from "lucide-react";
import { api, post, time, useApi } from "@/lib/api";
import { SOURCE_ICON } from "@/components/EvidenceViewer";
import { Disclaimer } from "@/components/ui";
import { LangToggle } from "@/lib/i18n";

const SPHERE: Record<string, string> = { AG: "AG-Sphäre", AN: "AN-Sphäre", neutral: "neutral" };

type RecTarget = { kind: "memo" } | { kind: "photo" };
/** Foto wartet auf Beschreibung: neu aufgenommen (file) oder ältere Erfassung mit offener Rückfrage (cid). */
type PhotoSheet = { url: string; file?: File; cid?: string; question?: string; at?: string };

/** Baustellen-Modus: nur Erfassung. Aufnahme per MediaRecorder (kein App-Store nötig), Transkription lokal (Whisper).
 *  Foto → sofort Fenster: Beschreibung per Sprache oder Notiz → Foto + Beschreibung werden zusammen gespeichert. */
export default function MobileCapture() {
  const { pid } = useParams<{ pid: string }>();
  const today = new Date().toISOString().slice(0, 10);
  const { data: caps, reload } = useApi<any[]>(`/api/projects/${pid}/captures?date=${today}`, 4000);
  const { data: events, reload: reloadEvents } = useApi<any[]>(`/api/projects/${pid}/events?date=${today}`, 6000);
  const [rec, setRec] = useState<MediaRecorder | null>(null);
  const [recFor, setRecFor] = useState<RecTarget | null>(null);
  const [secs, setSecs] = useState(0);
  const [hint, setHint] = useState("");
  const [note, setNote] = useState("");
  const [sheet, setSheet] = useState<PhotoSheet | null>(null);
  const [sheetMode, setSheetMode] = useState<"choose" | "note">("choose");
  const [sheetText, setSheetText] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const chunks = useRef<Blob[]>([]);
  const { t, lang } = useT();
  const speech = useRef<any>(null);
  const hintRef = useRef("");
  const sheetRef = useRef<PhotoSheet | null>(null); // Aufnahme-Callback liest das aktuelle Foto, nicht das beim Start
  const gps = useRef<{ lat: number; lon: number } | null>(null);

  useEffect(() => {
    navigator.geolocation?.getCurrentPosition((p) => (gps.current = { lat: p.coords.latitude, lon: p.coords.longitude }), () => {}, { timeout: 5000 });
  }, []);
  useEffect(() => {
    if (!rec) return;
    const t = setInterval(() => setSecs((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [rec]);

  const openSheet = (sh: PhotoSheet) => {
    sheetRef.current = sh;
    setSheet(sh);
    setSheetMode("choose");
    setSheetText("");
  };
  const closeSheet = () => {
    if (sheetRef.current?.file) URL.revokeObjectURL(sheetRef.current.url);
    sheetRef.current = null;
    setSheet(null);
  };

  const flash = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 3000);
  };

  const upload = async (kind: string, file?: Blob, filename?: string, text?: string, transcriptHint?: string) => {
    setBusy(true);
    const fd = new FormData();
    fd.append("kind", kind);
    if (file) fd.append("file", file, filename);
    if (text) fd.append("text", text);
    if (transcriptHint) fd.append("transcript_hint", transcriptHint);
    fd.append("language", lang);
    if (gps.current) { fd.append("lat", String(gps.current.lat)); fd.append("lon", String(gps.current.lon)); }
    try {
      await api(`/api/projects/${pid}/captures`, { method: "POST", body: fd });
      flash(kind === "photo" ? t("Foto übertragen – KI wertet aus, danach eine Rückfrage") : t("Übertragen – wird ausgewertet"));
      setTimeout(reload, 1500);
    } catch (e: any) {
      flash(t("Fehler: {e}", { e: e.message }));
    } finally {
      setBusy(false);
    }
  };

  /** Foto + Beschreibung in einem Upload (neu) bzw. Antwort auf eine ältere offene Rückfrage (cid). */
  const savePhoto = async (sh: PhotoSheet, mode: "audio" | "note" | "none", opts: { blob?: Blob; filename?: string; text?: string } = {}) => {
    setBusy(true);
    const fd = new FormData();
    let url: string;
    if (sh.cid) {
      url = `/api/captures/${sh.cid}/answer`;
      fd.append("mode", mode === "none" ? "skip" : mode);
      if (opts.blob) fd.append("file", opts.blob, opts.filename);
      if (opts.text) fd.append("text", opts.text);
    } else {
      url = `/api/projects/${pid}/captures`;
      fd.append("kind", "photo");
      fd.append("file", sh.file!, sh.file!.name);
      fd.append("language", lang);
      fd.append("description_mode", mode);
      if (opts.blob) fd.append("description_audio", opts.blob, opts.filename);
      if (opts.text) fd.append(mode === "audio" ? "transcript_hint" : "description_text", opts.text);
      if (gps.current) { fd.append("lat", String(gps.current.lat)); fd.append("lon", String(gps.current.lon)); }
    }
    try {
      await api(url, { method: "POST", body: fd });
      flash(mode === "none" ? t("Foto ohne Beschreibung gespeichert") : t("Foto mit Beschreibung übertragen – wird ausgewertet"));
      closeSheet();
      setTimeout(() => { reload(); reloadEvents(); }, 1500);
    } catch (e: any) {
      flash(t("Fehler: {e}", { e: e.message }));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (c: any) => {
    if (!window.confirm(t("„{x}“ löschen? Abgeleitete Mengen, Belege und Ereignisse werden mit entfernt (Audit-Log).", { x: t(c.title) }))) return;
    try {
      await api(`/api/captures/${c.capture_id}`, { method: "DELETE" });
      flash(t("Gelöscht"));
      reload();
    } catch (e: any) {
      flash(t("Fehler: {e}", { e: e.message }));
    }
  };

  /** Ein Tipp: Sphäre (Regel-Vorschlag) bestätigen; bei Anzeige-Pflicht zusätzlich Entwurf anlegen (Prüfung im Büro). */
  const confirmEvent = async (e: any) => {
    try {
      await post(`/api/events/${e.event_id}/sphere`, { sphere: e.sphere });
      if (e.recommended_document?.requires_letter && !e.letter) {
        await post(`/api/events/${e.event_id}/draft`, { language: lang });
        flash(t("{d} als Entwurf angelegt – Prüfung im Büro", { d: t(e.recommended_document.label) }));
      } else flash(t("Im Bautagebuch dokumentiert"));
      reloadEvents();
    } catch (err: any) {
      flash(t("Fehler: {e}", { e: err.message }));
    }
  };

  const start = async (target: RecTarget) => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      const mime = ["audio/webm;codecs=opus", "audio/mp4", "audio/webm"].find((m) => MediaRecorder.isTypeSupported(m)) || "";
      const r = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      chunks.current = [];
      r.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
      r.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        const type = r.mimeType || "audio/webm";
        const blob = new Blob(chunks.current, { type });
        const hhmm = new Date().toTimeString().slice(0, 5).replace(":", "");
        const name = `rec_${hhmm}_${Date.now() % 100000}.${type.includes("mp4") ? "m4a" : "webm"}`;
        const sh = sheetRef.current;
        if (target.kind === "photo" && sh) savePhoto(sh, "audio", { blob, filename: name, text: hintRef.current || undefined });
        else upload("audio", blob, name, undefined, hintRef.current || undefined);
      };
      r.start(1000);
      setRec(r);
      setRecFor(target);
      setSecs(0);
      setHint("");
      hintRef.current = "";
      // Optional: Live-Text des Browsers nur als Vorschau/Fallback im Demo-Modus; maßgeblich ist Whisper auf dem Server
      const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
      if (SR) {
        const s = new SR();
        s.lang = lang === "en" ? "en-GB" : "de-DE";
        s.continuous = true;
        s.interimResults = true;
        s.onresult = (ev: any) => {
          const txt = Array.from(ev.results).map((x: any) => x[0].transcript).join(" ");
          hintRef.current = txt;
          setHint(txt);
        };
        s.start();
        speech.current = s;
      }
    } catch {
      flash(t("Mikrofon nicht verfügbar (HTTPS bzw. Berechtigung nötig)"));
    }
  };
  const stop = () => {
    speech.current?.stop();
    rec?.stop();
    setRec(null);
    setRecFor(null);
  };
  const recMemo = rec && recFor?.kind === "memo";
  const recPhoto = rec && recFor?.kind === "photo";
  const evById: Record<string, any> = Object.fromEntries((events || []).map((e) => [e.event_id, e]));

  return (
    <div className="min-h-screen w-full overflow-x-hidden bg-slate-900">
    <div className="mx-auto flex min-h-screen w-full max-w-md flex-col gap-4 p-4 text-white">
      <header className="flex items-center justify-between">
        <div><div className="text-xs text-slate-500">{t("Baustelle")}</div><div className="font-semibold">{pid.replace("-", " ")}</div></div>
        <div className="flex items-center gap-2"><LangToggle dark /><Link href={`/p/${pid}`} className="rounded-md bg-slate-800 p-2"><Monitor className="h-5 w-5" /></Link></div>
      </header>

      {/* Hauptaktion: Foto. Danach sofort das Beschreibungsfenster (Sprache oder Notiz). */}
      <label className={`flex aspect-square w-full cursor-pointer flex-col items-center justify-center gap-2 rounded-3xl bg-yellow-400 text-lg font-semibold text-slate-900 transition ${busy || rec ? "pointer-events-none opacity-40" : ""}`}>
        <Camera className="h-16 w-16" />
        {t("Foto")}
        <span className="px-6 text-center text-xs font-normal opacity-70">{t("Foto aufnehmen, danach kurz beschreiben – per Sprache oder Notiz")}</span>
        <input type="file" accept="image/*" capture="environment" className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) openSheet({ file: f, url: URL.createObjectURL(f) }); e.target.value = ""; }} />
      </label>

      <div className="grid grid-cols-2 gap-3">
        <button onClick={recMemo ? stop : () => start({ kind: "memo" })} disabled={busy || !!recPhoto}
          className={`flex flex-col items-center justify-center gap-1 rounded-2xl p-4 ${recMemo ? "animate-pulse bg-bad" : "bg-slate-800"} disabled:opacity-40`}>
          {recMemo ? <Square className="h-8 w-8" /> : <Mic className="h-8 w-8" />}
          {recMemo ? `${t("Stopp")} · ${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}` : t("Sprachmemo")}
        </button>
        <div className="flex flex-col gap-2 rounded-2xl bg-slate-800 p-2">
          <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3} placeholder={t("Notiz / Stichworte")}
            className="w-full flex-1 rounded-lg bg-slate-900 p-2 text-sm text-white placeholder:text-slate-600" />
          <button disabled={!note.trim() || busy} onClick={() => { upload("note", undefined, undefined, note); setNote(""); }}
            className="flex items-center justify-center gap-1 rounded-lg bg-slate-700 py-1.5 text-sm disabled:opacity-40"><Send className="h-[18px] w-[18px]" /> {t("Senden")}</button>
        </div>
      </div>
      {recMemo && hint && <p className="rounded-lg bg-slate-800 p-2 text-sm text-slate-300">{hint}</p>}

      {toast && <div className="rounded-lg bg-slate-700 px-3 py-2 text-sm">{toast}</div>}

      <section>
        <div className="mb-2 text-xs text-slate-500">{t("Heute erfasst")}</div>
        <ul className="space-y-1.5">
          {(caps || []).slice().reverse().map((c) => {
            const Icon = SOURCE_ICON[c.kind] || SOURCE_ICON.note;
            const waiting = c.kind === "photo" && c.status === "awaiting_answer";
            const evs = (c.event_ids || []).map((id: string) => evById[id]).filter(Boolean);
            return (
              <li key={c.capture_id} className="rounded-lg bg-slate-800 p-2 text-sm">
                <div className="flex items-start gap-2">
                  <Icon className="mt-0.5 h-4 w-4 shrink-0 text-slate-500" />
                  <div className="min-w-0 flex-1"><div className="flex gap-2"><span className="font-mono text-xs text-slate-500">{time(c.captured_at)}</span><span className="truncate">{t(c.title)}</span></div>
                    <div className="truncate text-xs text-slate-500">{c.summary}</div></div>
                  {waiting ? (
                    <button onClick={() => openSheet({ cid: c.capture_id, url: `/files/${c.file}`, question: c.followup?.question, at: c.captured_at })}
                      className="rounded bg-yellow-400 px-2 py-0.5 text-xs font-semibold text-slate-900">{t("Beschreiben")}</button>
                  ) : c.status === "done" ? <Check className="h-[18px] w-[18px] text-ok" /> : c.status === "error" ? <span className="text-xs text-bad" title={c.error}>{t("Fehler")}</span> : <Loader2 className="h-[18px] w-[18px] animate-spin" />}
                  <button onClick={() => remove(c)} className="rounded p-1 text-slate-400 hover:bg-slate-700 hover:text-bad" aria-label={t("Löschen")}><Trash2 className="h-[18px] w-[18px]" /></button>
                </div>
                {(c.hints || []).map((h: string) => <p key={h} className="mt-1 pl-6 text-xs text-sky-300">{t(h)}</p>)}
                {c.status === "done" && evs.map((e: any) => (
                  <div key={e.event_id} className="mt-1.5 flex items-center gap-2 rounded bg-slate-900 px-2 py-1.5 pl-6 text-xs">
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium">{t(e.label)} · {t(SPHERE[e.sphere] || e.sphere)}</div>
                      <div className="truncate text-slate-400">→ {t(e.recommended_document.label)}{e.warnings?.length ? ` · ${t(e.warnings[0])}` : ""}</div>
                    </div>
                    {e.sphere_confirmed || e.letter
                      ? <span className="text-ok">{e.letter ? t("Entwurf") : t("bestätigt")}</span>
                      : <button onClick={() => confirmEvent(e)} className="rounded bg-yellow-400 px-2 py-1 font-semibold text-slate-900">{t("Bestätigen")}</button>}
                  </div>
                ))}
              </li>
            );
          })}
        </ul>
      </section>
      <Disclaimer className="mt-auto !text-slate-600" />

      {/* Beschreibungsfenster direkt nach dem Foto: Sprache oder Notiz – beides wird mit dem Foto gespeichert */}
      {sheet && (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/70 sm:items-center" role="dialog" aria-modal="true">
          <div className="max-h-[92vh] w-full max-w-md space-y-3 overflow-y-auto rounded-t-3xl bg-slate-800 p-4 text-white sm:rounded-3xl">
            <div className="flex items-center justify-between">
              <div className="text-base font-semibold">{t("Foto beschreiben")}{sheet.at ? ` · ${time(sheet.at)}` : ""}</div>
              <button onClick={closeSheet} disabled={busy || !!recPhoto} className="rounded-md p-1 text-slate-400 hover:bg-slate-700 disabled:opacity-40" aria-label={t("Abbrechen")}><X className="h-6 w-6" /></button>
            </div>
            <img src={sheet.url} alt="" className="max-h-64 w-full rounded-lg bg-slate-900 object-contain" />
            <p className="text-sm leading-snug text-slate-300">{sheet.question ? t(sheet.question) : t("Was ist zu sehen – und warum? Wer, seit wann, welche Arbeiten, wie viel?")}</p>

            {sheetMode === "choose" && (
              <>
                <button onClick={recPhoto ? stop : () => start({ kind: "photo" })} disabled={busy || !!recMemo}
                  className={`flex w-full items-center justify-center gap-2 rounded-xl py-4 text-base font-semibold ${recPhoto ? "animate-pulse bg-bad" : "bg-yellow-400 text-slate-900"} disabled:opacity-40`}>
                  {recPhoto ? <Square className="h-6 w-6" /> : <Mic className="h-6 w-6" />}
                  {recPhoto ? `${t("Stopp & speichern")} · ${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}` : t("Per Sprache beschreiben")}
                </button>
                {recPhoto && hint && <p className="rounded-lg bg-slate-900 p-2 text-sm text-slate-300">{hint}</p>}
                <button onClick={() => setSheetMode("note")} disabled={busy || !!rec}
                  className="flex w-full items-center justify-center gap-2 rounded-xl bg-slate-700 py-4 text-base font-semibold disabled:opacity-40">
                  <PencilLine className="h-6 w-6" /> {t("Als Notiz beschreiben")}
                </button>
              </>
            )}
            {sheetMode === "note" && (
              <div className="space-y-2">
                <textarea autoFocus value={sheetText} onChange={(e) => setSheetText(e.target.value)} rows={4}
                  placeholder={t("z. B. „Riss in der Wand Achse C, Vorleistung Rohbauer, seit heute Morgen“")}
                  className="w-full rounded-lg bg-slate-900 p-2 text-sm text-white placeholder:text-slate-600" />
                <div className="flex gap-2">
                  <button onClick={() => setSheetMode("choose")} disabled={busy} className="rounded-lg bg-slate-700 px-3 py-2 text-sm disabled:opacity-40">{t("Zurück")}</button>
                  <button disabled={!sheetText.trim() || busy} onClick={() => savePhoto(sheet, "note", { text: sheetText.trim() })}
                    className="flex flex-1 items-center justify-center gap-1 rounded-lg bg-yellow-400 py-2 text-sm font-semibold text-slate-900 disabled:opacity-40">
                    <Send className="h-[18px] w-[18px]" /> {t("Foto + Notiz speichern")}</button>
                </div>
              </div>
            )}
            <button disabled={busy || !!rec} onClick={() => savePhoto(sheet, "none")}
              className="flex w-full items-center justify-center gap-1 rounded-lg py-2 text-sm text-slate-400 hover:bg-slate-700 disabled:opacity-40">
              <SkipForward className="h-4 w-4" /> {t("Ohne Beschreibung speichern")}</button>
            <p className="text-[11px] leading-snug text-slate-500">{t("Ursache, Verursacher und Mengen kommen nur aus Ihrer Beschreibung – nicht aus dem Foto.")}</p>
          </div>
        </div>
      )}
    </div>
    </div>
  );
}
