"use client";
/**
 * Rechtsgrundlage hinzufügen oder neue Fassung hochladen. Gilt für alle Projekte.
 * Bei „neue Fassung“ wird die alte archiviert (nicht gelöscht – bestehende Schreiben können sich darauf stützen).
 */
import { useState } from "react";
import { Scale, Upload, X } from "lucide-react";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";

export default function LegalUpload({ replaces, onClose, onDone }: { replaces?: any; onClose: () => void; onDone: () => void }) {
  const { t } = useT();
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState(replaces?.title || "");
  const [version, setVersion] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const save = async () => {
    if (!file) return;
    setBusy(true); setErr(null);
    const fd = new FormData();
    fd.append("file", file, file.name);
    fd.append("title", title.trim());
    if (version.trim()) fd.append("version", version.trim());
    if (replaces) fd.append("replaces", replaces.doc_id);
    try { await api(`/api/legal`, { method: "POST", body: fd }); onDone(); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  const input = "mt-0.5 w-full rounded border px-2 py-1.5 text-sm text-slate-900";
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={() => !busy && onClose()}>
      <div className="w-full max-w-lg rounded-lg bg-white shadow-2xl" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <header className="flex items-center gap-2 border-b px-4 py-3">
          <Scale className="h-[18px] w-[18px]" />
          <h3 className="flex-1 font-semibold">{t(replaces ? "Neue Fassung hochladen" : "Rechtsgrundlage hinzufügen")}</h3>
          <button className="rounded p-1 hover:bg-slate-100" onClick={onClose} disabled={busy} aria-label={t("Schließen")}><X className="h-[18px] w-[18px]" /></button>
        </header>
        <div className="space-y-3 p-4">
          {replaces && (
            <p className="rounded bg-warn-soft p-2 text-xs text-warn-text">
              {t("Ersetzt „{x}“. Die bisherige Fassung wird archiviert und nicht mehr für neue Schreiben herangezogen; bereits erstellte Schreiben behalten ihren Bezug.", { x: replaces.title })}
            </p>
          )}
          <label className="block text-xs text-slate-600">{t("Titel")}
            <input className={input} value={title} placeholder="VOB/B 2026" onChange={(e) => setTitle(e.target.value)} /></label>
          <label className="block text-xs text-slate-600">{t("Fassung / Stand")}
            <input className={input} value={version} placeholder={t("z. B. Ausgabe 2026, Stand 01.10.2026")} onChange={(e) => setVersion(e.target.value)} /></label>
          <label className="flex cursor-pointer flex-col items-center gap-1 rounded-md border-2 border-dashed border-slate-300 p-4 text-center text-sm text-slate-600 hover:bg-slate-50"
            onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); setFile(e.dataTransfer.files?.[0] || null); }}>
            <Upload className="h-5 w-5" />
            {file ? <span className="font-medium text-slate-900">{file.name}</span> : t("PDF (mit Textebene), DOCX, TXT oder MD hierher ziehen oder auswählen")}
            <input type="file" className="hidden" accept=".pdf,.docx,.txt,.md" onChange={(e) => setFile(e.target.files?.[0] || null)} />
          </label>
          <p className="text-2xs text-slate-600">{t("Gilt für alle Projekte. Der Text wird je Paragraph (§) in die Suche aufgenommen.")}</p>
          {err && <p className="text-xs text-bad-text">{err}</p>}
        </div>
        <div className="flex justify-end gap-2 border-t px-4 py-3">
          <button className="btn" onClick={onClose} disabled={busy}>{t("Abbrechen")}</button>
          <button className="btn-primary" onClick={save} disabled={!file || busy}><Upload className="h-[18px] w-[18px]" /> {busy ? t("wird eingelesen …") : t("Hochladen")}</button>
        </div>
      </div>
    </div>
  );
}
