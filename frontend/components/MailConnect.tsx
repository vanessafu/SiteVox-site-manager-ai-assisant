"use client";
import { useEffect, useState } from "react";
import { Lock, X } from "lucide-react";
import { post, useApi } from "@/lib/api";
import { useT } from "@/lib/i18n";

type Preset = { label: string; imap_host: string; imap_port: number; hint: string; disabled?: boolean };

/** Fenster „Postfach verbinden“: Anbieter wählen, Zugang testen, Konto anlegen (Passwort nur im Arbeitsspeicher). */
export default function MailConnect({ pid, onClose, onDone }: { pid: string; onClose: () => void; onDone: (acc: any) => void }) {
  const { t } = useT();
  const { data: presets } = useApi<Record<string, Preset>>("/api/mail-providers");
  const [provider, setProvider] = useState("gmail");
  const [f, setF] = useState({ address: "", username: "", password: "", imap_host: "imap.gmail.com", imap_port: 993,
    security: "ssl", folder: "INBOX", since_days: 14, only_project: true, smtp_host: "", smtp_port: "" as number | "" });
  const [advanced, setAdvanced] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const p = presets?.[provider];
  const set = (k: string, v: any) => setF((x) => ({ ...x, [k]: v }));
  useEffect(() => {
    if (p) setF((x) => ({ ...x, imap_host: p.imap_host, imap_port: p.imap_port }));
    if (provider === "imap") setAdvanced(true);
  }, [provider, p]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  const submit = async () => {
    setBusy(true); setErr(null);
    try { onDone(await post(`/api/projects/${pid}/mail-accounts`, { provider, ...f })); }
    catch (e: any) { setErr(e.message); }
    finally { setBusy(false); }
  };
  const field = "w-full rounded-md border px-3 py-2 text-sm";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/30 p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" className="card max-h-[90vh] w-full max-w-xl overflow-y-auto bg-white shadow-xl" onClick={(e) => e.stopPropagation()}>
        <header className="flex items-start gap-2 border-b p-5">
          <div className="flex-1">
            <h2 className="text-lg font-semibold">{t("Postfach verbinden")}</h2>
            <p className="mt-0.5 text-sm text-slate-600">{t("E-Mails zu diesem Projekt werden abgeholt, zugeordnet und ausgewertet. Nur lesender Zugriff – nichts wird gelöscht oder als gelesen markiert.")}</p>
          </div>
          <button onClick={onClose} className="rounded p-1 hover:bg-slate-100" aria-label={t("Schließen")}><X className="h-5 w-5" /></button>
        </header>
        <div className="space-y-4 p-5">
          <div>
            <div className="mb-2 text-sm font-medium">{t("Anbieter")}</div>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {presets && Object.entries(presets).map(([k, v]) => (
                <button key={k} disabled={v.disabled} onClick={() => setProvider(k)} title={v.disabled ? t(v.hint) : ""}
                  className={`rounded-md border px-3 py-2 text-left text-sm disabled:cursor-not-allowed disabled:opacity-45 ${provider === k ? "border-slate-900 bg-slate-900 text-white" : "hover:bg-slate-50"}`}>
                  {t(v.label)}{v.disabled && <span className="block text-2xs">{t("folgt (OAuth)")}</span>}
                </button>
              ))}
            </div>
            {p?.hint && <p className="mt-2 text-xs text-slate-600">{t(p.hint)}</p>}
          </div>
          <label className="block space-y-1"><span className="text-sm font-medium">{t("E-Mail-Adresse")}</span>
            <input className={field} type="email" autoComplete="off" placeholder="bauleitung@firma.de" value={f.address} onChange={(e) => set("address", e.target.value)} /></label>
          <label className="block space-y-1"><span className="text-sm font-medium">{t("App-Passwort")}</span>
            <input className={field} type="password" autoComplete="new-password" value={f.password} onChange={(e) => set("password", e.target.value)} onKeyDown={(e) => e.key === "Enter" && submit()} /></label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={f.only_project} onChange={(e) => set("only_project", e.target.checked)} />
            {t("Nur E-Mails übernehmen, die diesem Projekt zugeordnet werden (Vertragsnummer, Projektname, bekannte Absender)")}
          </label>
          <button className="text-sm text-slate-600 underline-offset-2 hover:underline" onClick={() => setAdvanced((a) => !a)}>{t(advanced ? "Erweiterte Einstellungen ausblenden" : "Erweiterte Einstellungen")}</button>
          {advanced && (
            <div className="grid grid-cols-2 gap-3 rounded-md bg-slate-50 p-3">
              <label className="col-span-2 block space-y-1 sm:col-span-1"><span className="text-xs">{t("IMAP-Server")}</span><input className={field} value={f.imap_host} onChange={(e) => set("imap_host", e.target.value)} /></label>
              <label className="block space-y-1"><span className="text-xs">{t("Port")}</span><input className={field} type="number" value={f.imap_port} onChange={(e) => set("imap_port", Number(e.target.value))} /></label>
              <label className="block space-y-1"><span className="text-xs">{t("Verschlüsselung")}</span>
                <select className={field} value={f.security} onChange={(e) => set("security", e.target.value)}><option value="ssl">SSL/TLS</option><option value="starttls">STARTTLS</option></select></label>
              <label className="block space-y-1"><span className="text-xs">{t("Benutzername (falls abweichend)")}</span><input className={field} value={f.username} onChange={(e) => set("username", e.target.value)} /></label>
              <label className="block space-y-1"><span className="text-xs">{t("Ordner")}</span><input className={field} value={f.folder} onChange={(e) => set("folder", e.target.value)} /></label>
              <label className="col-span-2 block space-y-1 sm:col-span-1"><span className="text-xs">{t("SMTP-Server (Versand, leer = automatisch)")}</span><input className={field} placeholder="smtp.firma.de" value={f.smtp_host} onChange={(e) => set("smtp_host", e.target.value)} /></label>
              <label className="block space-y-1"><span className="text-xs">{t("SMTP-Port")}</span><input className={field} type="number" placeholder="465" value={f.smtp_port} onChange={(e) => set("smtp_port", e.target.value === "" ? "" : Number(e.target.value))} /></label>
              <label className="block space-y-1"><span className="text-xs">{t("Zeitraum (Tage)")}</span><input className={field} type="number" min={1} max={365} value={f.since_days} onChange={(e) => set("since_days", Number(e.target.value))} /></label>
            </div>
          )}
          <p className="flex gap-2 rounded-md bg-slate-50 p-3 text-xs leading-relaxed text-slate-600"><Lock className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {t("Das Passwort wird nicht gespeichert, sondern nur im Arbeitsspeicher des lokalen Servers gehalten. Nach einem Neustart muss es erneut eingegeben werden.")}</p>
          {err && <p className="rounded-md bg-bad-soft p-3 text-sm text-bad-text">{err}</p>}
        </div>
        <footer className="flex justify-end gap-2 border-t p-4">
          <button className="btn" onClick={onClose}>{t("Abbrechen")}</button>
          <button className="btn-primary" disabled={busy || !f.address || !f.password || !!p?.disabled} onClick={submit}>{busy ? t("Verbindung wird getestet …") : t("Verbinden & testen")}</button>
        </footer>
      </div>
    </div>
  );
}
