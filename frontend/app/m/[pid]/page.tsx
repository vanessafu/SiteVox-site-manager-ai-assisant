"use client";
import { useT } from "@/lib/i18n";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Camera, Check, Loader2, Mic, Monitor, Send, Square, Trash2 } from "lucide-react";
import { api, time, useApi } from "@/lib/api";
import { SOURCE_ICON } from "@/components/EvidenceViewer";
import { Disclaimer } from "@/components/ui";
import { LangToggle } from "@/lib/i18n";

/** Baustellen-Modus: nur Erfassung. Aufnahme per MediaRecorder (kein App-Store nötig), Transkription lokal (Whisper). */
export default function MobileCapture() {
  const { pid } = useParams<{ pid: string }>();
  const today = new Date().toISOString().slice(0, 10);
  const { data: caps, reload } = useApi<any[]>(`/api/projects/${pid}/captures?date=${today}`, 4000);
  const [rec, setRec] = useState<MediaRecorder | null>(null);
  const [secs, setSecs] = useState(0);
  const [hint, setHint] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const chunks = useRef<Blob[]>([]);
  const { t, lang } = useT();
  const speech = useRef<any>(null);
  const gps = useRef<{ lat: number; lon: number } | null>(null);

  useEffect(() => {
    navigator.geolocation?.getCurrentPosition((p) => (gps.current = { lat: p.coords.latitude, lon: p.coords.longitude }), () => {}, { timeout: 5000 });
  }, []);
  useEffect(() => {
    if (!rec) return;
    const t = setInterval(() => setSecs((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [rec]);

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
      setToast(t("Übertragen – wird ausgewertet"));
      setTimeout(reload, 1500);
    } catch (e: any) {
      setToast(t("Fehler: {e}", { e: e.message }));
    } finally {
      setBusy(false);
      setTimeout(() => setToast(null), 3000);
    }
  };

  const remove = async (c: any) => {
    if (!window.confirm(t("„{x}“ löschen? Abgeleitete Mengen, Belege und Ereignisse werden mit entfernt (Audit-Log).", { x: t(c.title) }))) return;
    try {
      await api(`/api/captures/${c.capture_id}`, { method: "DELETE" });
      setToast(t("Gelöscht"));
      reload();
    } catch (e: any) {
      setToast(t("Fehler: {e}", { e: e.message }));
    }
    setTimeout(() => setToast(null), 3000);
  };

  const start = async () => {
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
        upload("audio", blob, `rec_${hhmm}_${Date.now() % 100000}.${type.includes("mp4") ? "m4a" : "webm"}`, undefined, hint || undefined);
      };
      r.start(1000);
      setRec(r);
      setSecs(0);
      setHint("");
      // Optional: Live-Text des Browsers nur als Vorschau/Fallback im Demo-Modus; maßgeblich ist Whisper auf dem Server
      const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
      if (SR) {
        const s = new SR();
        s.lang = lang === "en" ? "en-GB" : "de-DE";
        s.continuous = true;
        s.interimResults = true;
        s.onresult = (ev: any) => setHint(Array.from(ev.results).map((x: any) => x[0].transcript).join(" "));
        s.start();
        speech.current = s;
      }
    } catch {
      setToast(t("Mikrofon nicht verfügbar (HTTPS bzw. Berechtigung nötig)"));
    }
  };
  const stop = () => {
    speech.current?.stop();
    rec?.stop();
    setRec(null);
  };

  return (
    <div className="min-h-screen w-full overflow-x-hidden bg-slate-900">
    <div className="mx-auto flex min-h-screen w-full max-w-md flex-col gap-4 p-4 text-white">
      <header className="flex items-center justify-between">
        <div><div className="text-xs text-slate-500">{t("Baustelle")}</div><div className="font-semibold">{pid.replace("-", " ")}</div></div>
        <div className="flex items-center gap-2"><LangToggle dark /><Link href={`/p/${pid}`} className="rounded-md bg-slate-800 p-2"><Monitor className="h-5 w-5" /></Link></div>
      </header>

      <button onClick={rec ? stop : start} disabled={busy}
        className={`flex aspect-square w-full flex-col items-center justify-center gap-2 rounded-3xl text-lg font-semibold transition ${rec ? "animate-pulse bg-bad" : "bg-yellow-400 text-slate-900"}`}>
        {rec ? <Square className="h-16 w-16" /> : <Mic className="h-16 w-16" />}
        {rec ? `${t("Stopp")} · ${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}` : t("Sprachmemo")}
        {!rec && <span className="text-xs font-normal opacity-70">{t("z. B. „Bagger steht seit 10 Uhr, Hydraulikschlauch …“")}</span>}
      </button>
      {rec && hint && <p className="rounded-lg bg-slate-800 p-2 text-sm text-slate-300">{hint}</p>}

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
            return (
              <li key={c.capture_id} className="flex items-start gap-2 rounded-lg bg-slate-800 p-2 text-sm">
                <Icon className="mt-0.5 h-4 w-4 shrink-0 text-slate-500" />
                <div className="min-w-0 flex-1"><div className="flex gap-2"><span className="font-mono text-xs text-slate-500">{time(c.captured_at)}</span><span className="truncate">{t(c.title)}</span></div>
                  <div className="truncate text-xs text-slate-500">{c.summary}</div></div>
                {c.status === "done" ? <Check className="h-[18px] w-[18px] text-ok" /> : <Loader2 className="h-[18px] w-[18px] animate-spin" />}
                <button onClick={() => remove(c)} className="rounded p-1 text-slate-400 hover:bg-slate-700 hover:text-bad" aria-label={t("Löschen")}><Trash2 className="h-[18px] w-[18px]" /></button>
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
