"use client";
import { useT } from "@/lib/i18n";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Camera, Check, Clock, ImagePlus, Loader2, Mic, Monitor, Send, SkipForward, Square, Trash2 } from "lucide-react";
import { api, post, time, useApi } from "@/lib/api";
import { SOURCE_ICON } from "@/components/EvidenceViewer";
import { Disclaimer } from "@/components/ui";
import { LangToggle } from "@/lib/i18n";

const OBS_LABEL: Record<string, string> = {
  blocked_access: "Zugang/Zufahrt blockiert", standing_water: "stehendes Wasser", material_storage: "Material auf der Arbeitsfläche",
  equipment_idle: "Gerät steht still", crack: "Riss", surface_defect: "Oberflächenfehler", damage: "Beschädigung",
  stage_change: "Bauzustand / Fortschritt", safety_hazard: "Sicherheitsmangel", other: "Sonstiges",
};
const OBS_COLOR: Record<string, string> = {
  obstruction: "border-orange-400", defect: "border-red-500", progress: "border-sky-400", safety: "border-fuchsia-500",
};
const SPHERE: Record<string, string> = { AG: "AG-Sphäre", AN: "AN-Sphäre", neutral: "neutral" };

type RecTarget = { kind: "memo" } | { kind: "answer"; cid: string };

/** Foto mit KI-Boxen (bbox relativ 0–1000). Die Boxen markieren nur, was die KI gesehen hat – kein Beleg. */
function PhotoWithBoxes({ cap }: { cap: any }) {
  const obs = cap.vision?.analysis?.observations || [];
  if (!cap.file) return null;
  return (
    <div className="relative w-full overflow-hidden rounded-lg">
      <img src={`/files/${cap.file}`} alt={cap.title} className="block w-full" />
      {obs.map((o: any, i: number) => o.bbox && (
        <div key={i} className={`absolute border-2 ${OBS_COLOR[o.category] || "border-yellow-400"}`}
          style={{ left: `${o.bbox[0] / 10}%`, top: `${o.bbox[1] / 10}%`, width: `${(o.bbox[2] - o.bbox[0]) / 10}%`, height: `${(o.bbox[3] - o.bbox[1]) / 10}%` }}>
          <span className="absolute left-0 top-0 bg-slate-900/80 px-1 text-[10px] leading-4">{i + 1}</span>
        </div>
      ))}
    </div>
  );
}

/** Baustellen-Modus: nur Erfassung. Aufnahme per MediaRecorder (kein App-Store nötig), Transkription lokal (Whisper).
 *  Foto → KI sagt, was zu sehen ist → genau eine Rückfrage → Antwort per Sprache oder Notiz (gleiche Erfassung). */
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
  const [answerText, setAnswerText] = useState("");
  const [detail, setDetail] = useState<File | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [later, setLater] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const chunks = useRef<Blob[]>([]);
  const { t, lang } = useT();
  const speech = useRef<any>(null);
  const hintRef = useRef("");
  const detailRef = useRef<File | null>(null); // Aufnahme-Callback liest den aktuellen Wert, nicht den beim Start
  const pickDetail = (f: File | null) => { detailRef.current = f; setDetail(f); };
  const gps = useRef<{ lat: number; lon: number } | null>(null);

  useEffect(() => {
    navigator.geolocation?.getCurrentPosition((p) => (gps.current = { lat: p.coords.latitude, lon: p.coords.longitude }), () => {}, { timeout: 5000 });
  }, []);
  useEffect(() => {
    if (!rec) return;
    const t = setInterval(() => setSecs((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [rec]);

  // Offene Rückfragen: neueste zuerst; "Später" blendet sie bis zum nächsten Antippen aus
  const pending = (caps || []).filter((c) => c.kind === "photo" && c.status === "awaiting_answer").reverse();
  const current = pending.find((c) => c.capture_id === active) || pending.find((c) => !later.includes(c.capture_id));
  useEffect(() => {
    setAnswerText("");
    pickDetail(null);
  }, [current?.capture_id]);

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

  const answer = async (cid: string, mode: "audio" | "note" | "skip", opts: { blob?: Blob; filename?: string; text?: string } = {}) => {
    setBusy(true);
    const fd = new FormData();
    fd.append("mode", mode);
    if (opts.blob) fd.append("file", opts.blob, opts.filename);
    if (opts.text) fd.append("text", opts.text);
    const d = detailRef.current;
    if (d && mode !== "skip") fd.append("detail_photo", d, d.name);
    try {
      await api(`/api/captures/${cid}/answer`, { method: "POST", body: fd });
      flash(mode === "skip" ? t("Foto ohne Antwort abgelegt") : t("Antwort übertragen – wird ausgewertet"));
      setActive(null);
      setAnswerText("");
      pickDetail(null);
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
        if (target.kind === "answer") answer(target.cid, "audio", { blob, filename: name, text: hintRef.current || undefined });
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
  const recAnswer = rec && recFor?.kind === "answer";
  const evById: Record<string, any> = Object.fromEntries((events || []).map((e) => [e.event_id, e]));

  return (
    <div className="min-h-screen w-full overflow-x-hidden bg-slate-900">
    <div className="mx-auto flex min-h-screen w-full max-w-md flex-col gap-4 p-4 text-white">
      <header className="flex items-center justify-between">
        <div><div className="text-xs text-slate-500">{t("Baustelle")}</div><div className="font-semibold">{pid.replace("-", " ")}</div></div>
        <div className="flex items-center gap-2"><LangToggle dark /><Link href={`/p/${pid}`} className="rounded-md bg-slate-800 p-2"><Monitor className="h-5 w-5" /></Link></div>
      </header>

      {/* Rückfrage zum Foto: KI = was ist zu sehen, Antwort = warum / wer / seit wann / wie viel */}
      {current && (
        <section className="space-y-3 rounded-2xl bg-slate-800 p-3 ring-2 ring-yellow-400">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span>{t("Rückfrage zum Foto {t}", { t: time(current.captured_at) })}</span>
            {pending.length > 1 && <span>{t("{n} offen", { n: pending.length })}</span>}
          </div>
          <PhotoWithBoxes cap={current} />
          {(current.vision?.analysis?.observations || []).length > 0 && (
            <div className="space-y-1">
              <div className="text-[11px] uppercase tracking-wide text-yellow-300">{t("KI-Beobachtung – kein Beleg")}</div>
              <ul className="space-y-0.5 text-xs text-slate-300">
                {current.vision.analysis.observations.map((o: any, i: number) => (
                  <li key={i}><span className="font-mono text-slate-500">{i + 1}</span> {t(OBS_LABEL[o.subtype] || o.subtype)}: {o.description}
                    <span className="text-slate-500"> · {Math.round((o.visual_conf ?? 0) * 100)} %</span></li>
                ))}
              </ul>
            </div>
          )}
          <p className="text-base font-semibold leading-snug">{t(current.followup?.question || "Was ist hier passiert?")}</p>

          <button onClick={recAnswer ? stop : () => start({ kind: "answer", cid: current.capture_id })} disabled={busy || !!recMemo}
            className={`flex w-full items-center justify-center gap-2 rounded-xl py-4 text-base font-semibold ${recAnswer ? "animate-pulse bg-bad" : "bg-yellow-400 text-slate-900"} disabled:opacity-40`}>
            {recAnswer ? <Square className="h-6 w-6" /> : <Mic className="h-6 w-6" />}
            {recAnswer ? `${t("Stopp")} · ${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}` : t("Antwort sprechen")}
          </button>
          {recAnswer && hint && <p className="rounded-lg bg-slate-900 p-2 text-sm text-slate-300">{hint}</p>}

          <div className="flex gap-2">
            <textarea value={answerText} onChange={(e) => setAnswerText(e.target.value)} rows={2} placeholder={t("… oder als Notiz antworten")}
              className="min-w-0 flex-1 rounded-lg bg-slate-900 p-2 text-sm text-white placeholder:text-slate-600" />
            <button disabled={!answerText.trim() || busy || !!rec} onClick={() => answer(current.capture_id, "note", { text: answerText })}
              className="rounded-lg bg-slate-700 px-3 disabled:opacity-40" aria-label={t("Senden")}><Send className="h-5 w-5" /></button>
          </div>

          {current.followup?.wants_detail_photo && (
            <label className="flex cursor-pointer items-center gap-2 rounded-lg bg-slate-900 px-3 py-2 text-sm">
              <ImagePlus className="h-5 w-5 shrink-0" />
              <span className="truncate">{detail ? detail.name : t("Detailfoto mit Maßstab anhängen (optional)")}</span>
              <input type="file" accept="image/*" capture="environment" className="hidden"
                onChange={(e) => { pickDetail(e.target.files?.[0] || null); e.target.value = ""; }} />
            </label>
          )}

          <div className="flex gap-2 text-sm">
            <button disabled={busy || !!rec} onClick={() => answer(current.capture_id, "skip")}
              className="flex flex-1 items-center justify-center gap-1 rounded-lg bg-slate-700 py-2 disabled:opacity-40"><SkipForward className="h-4 w-4" /> {t("Ohne Antwort ablegen")}</button>
            <button disabled={!!rec} onClick={() => { setLater((l) => [...l, current.capture_id]); setActive(null); }}
              className="flex flex-1 items-center justify-center gap-1 rounded-lg bg-slate-700 py-2 disabled:opacity-40"><Clock className="h-4 w-4" /> {t("Später")}</button>
          </div>
          <p className="text-[11px] leading-snug text-slate-500">{t("Die KI beschreibt nur, was zu sehen ist. Wer es verursacht hat und welches Schreiben nötig ist, ergibt sich aus Ihrer Antwort und dem Regelwerk.")}</p>
        </section>
      )}

      <button onClick={recMemo ? stop : () => start({ kind: "memo" })} disabled={busy || !!recAnswer}
        className={`flex w-full flex-col items-center justify-center gap-2 rounded-3xl text-lg font-semibold transition ${current ? "py-6" : "aspect-square"} ${recMemo ? "animate-pulse bg-bad" : "bg-yellow-400 text-slate-900"} disabled:opacity-40`}>
        {recMemo ? <Square className={current ? "h-8 w-8" : "h-16 w-16"} /> : <Mic className={current ? "h-8 w-8" : "h-16 w-16"} />}
        {recMemo ? `${t("Stopp")} · ${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}` : t("Sprachmemo")}
        {!rec && !current && <span className="text-xs font-normal opacity-70">{t("z. B. „Bagger steht seit 10 Uhr, Hydraulikschlauch …“")}</span>}
      </button>
      {recMemo && hint && <p className="rounded-lg bg-slate-800 p-2 text-sm text-slate-300">{hint}</p>}

      <div className="grid grid-cols-2 gap-3">
        <label className="flex cursor-pointer flex-col items-center gap-1 rounded-2xl bg-slate-800 p-4">
          <Camera className="h-8 w-8" /> {t("Foto")}
          <input type="file" accept="image/*" capture="environment" className="hidden"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) upload("photo", f, f.name); e.target.value = ""; }} />
        </label>
        <div className="flex flex-col gap-2 rounded-2xl bg-slate-800 p-2">
          <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3} placeholder={t("Notiz / Stichworte")}
            className="w-full flex-1 rounded-lg bg-slate-900 p-2 text-sm text-white placeholder:text-slate-600" />
          <button disabled={!note.trim() || busy} onClick={() => { upload("note", undefined, undefined, note); setNote(""); }}
            className="flex items-center justify-center gap-1 rounded-lg bg-slate-700 py-1.5 text-sm disabled:opacity-40"><Send className="h-[18px] w-[18px]" /> {t("Senden")}</button>
        </div>
      </div>

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
                    <button onClick={() => { setActive(c.capture_id); setLater((l) => l.filter((x) => x !== c.capture_id)); window.scrollTo({ top: 0, behavior: "smooth" }); }}
                      className="rounded bg-yellow-400 px-2 py-0.5 text-xs font-semibold text-slate-900">{t("Rückfrage")}</button>
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
    </div>
    </div>
  );
}
