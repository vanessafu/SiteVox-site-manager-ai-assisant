"use client";
/**
 * Sendedialog: nach der Freigabe das Schreiben über das im Projekt gebundene Postfach an den AG senden.
 * Erst „Jetzt senden“ löst den Versand aus (confirm: true) – die Freigabe selbst sendet nie.
 */
import Link from "next/link";
import { useEffect, useState } from "react";
import { AlertTriangle, Lock, Mail, Paperclip, Send, X } from "lucide-react";
import { api, post } from "@/lib/api";
import { useT } from "@/lib/i18n";

export default function SendDialog({ pid, lid, onClose, onSent }: { pid: string; lid: string; onClose: () => void; onSent: (letter: any) => void }) {
  const { t } = useT();
  const [pv, setPv] = useState<any>(null);
  const [acc, setAcc] = useState("");
  const [cc, setCc] = useState("");
  const [to, setTo] = useState("");
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = async () => {
    const d = await api(`/api/letters/${lid}/send-preview`);
    setPv(d);
    setTo((x) => x || d.to || "");
    setAcc((a) => a || d.accounts.find((x: any) => x.connected)?.account_id || d.accounts[0]?.account_id || "");
  };
  useEffect(() => { load().catch((e) => setErr(e.message)); }, [lid]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [busy, onClose]);

  const account = pv?.accounts.find((a: any) => a.account_id === acc);
  const unlock = async () => {
    setBusy(true); setErr(null);
    try { await post(`/api/projects/${pid}/mail-accounts/${acc}/unlock`, { password: pw }); setPw(""); await load(); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  const send = async () => {
    setBusy(true); setErr(null);
    try {
      const letter = await post(`/api/letters/${lid}/send-email`, {
        account_id: acc, confirm: true, to: to.trim(), cc: cc.split(/[,;\s]+/).filter(Boolean),
      });
      onSent(letter);
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  // „Postfach gesperrt“ löst sich hier im Dialog; alle anderen Hinweise blockieren
  const validTo = /^[^\s@,;]+@[^\s@,;]+\.[^\s@,;]+$/.test(to.trim());
  // im Dialog lösbar: gesperrtes Postfach (Passwort) und fehlende Empfänger-Adresse (Feld „An“)
  const blocking = (pv?.problems || []).filter((p: string) => !(p.startsWith("Postfach gesperrt") && account && !account.connected)
    && !p.startsWith("Keine E-Mail-Adresse des AG"));
  const canSend = pv && !blocking.length && account?.connected && validTo && !busy;
  const row = "grid grid-cols-[6rem_minmax(0,1fr)] items-start gap-2 py-1.5 text-sm";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={() => !busy && onClose()}>
      <div className="w-full max-w-xl rounded-lg bg-white shadow-2xl" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <header className="flex items-center gap-2 border-b px-4 py-3">
          <Mail className="h-[18px] w-[18px]" />
          <h3 className="flex-1 font-semibold">{t("Schreiben per E-Mail an den AG senden")}</h3>
          <button className="rounded p-1 hover:bg-slate-100" onClick={onClose} disabled={busy} aria-label={t("Schließen")}><X className="h-[18px] w-[18px]" /></button>
        </header>
        {!pv ? <div className="p-4 text-sm text-slate-500">{err || t("lädt …")}</div> : (
          <div className="space-y-2 p-4">
            <div className="divide-y divide-slate-100">
              <div className={row}><span className="text-xs text-slate-600">{t("Von")}</span>
                {pv.accounts.length ? (
                  <select className="rounded border px-2 py-1 text-sm" value={acc} onChange={(e) => setAcc(e.target.value)}>
                    {pv.accounts.map((a: any) => <option key={a.account_id} value={a.account_id}>{a.address}{a.connected ? "" : ` (${t("gesperrt")})`}</option>)}
                  </select>
                ) : <span className="text-sm text-bad-text">{t("Kein Postfach gebunden")} – <Link className="underline" href={`/p/${pid}/postfach`}>{t("Postfach verbinden")}</Link></span>}
              </div>
              {account && !account.connected && (
                <div className={row}><span className="text-xs text-slate-600"><Lock className="inline h-3.5 w-3.5" /> {t("Passwort")}</span>
                  <div className="flex gap-2">
                    <input type="password" className="flex-1 rounded border px-2 py-1 text-sm" placeholder={t("App-Passwort des Postfachs")} value={pw}
                      onChange={(e) => setPw(e.target.value)} onKeyDown={(e) => e.key === "Enter" && pw && unlock()} />
                    <button className="btn-xs" disabled={!pw || busy} onClick={unlock}>{t("Entsperren")}</button>
                  </div>
                </div>
              )}
              <div className={row}><span className="text-xs text-slate-600">{t("An")}</span>
                <div className="space-y-0.5">
                  <input type="email" className={`w-full rounded border px-2 py-1 text-sm font-semibold ${validTo ? "" : "border-bad"}`} value={to}
                    placeholder={t("E-Mail-Adresse des AG fehlt – bitte prüfen und eintragen")} onChange={(e) => setTo(e.target.value)} />
                  {to.trim() !== (pv.to || "") && validTo && <div className="text-2xs text-warn-text">{t("Geänderter Empfänger wird beim Senden gespeichert (Audit-Log)")}</div>}
                </div></div>
              <div className={row}><span className="text-xs text-slate-600">{t("Cc")}</span>
                <input className="rounded border px-2 py-1 text-sm" placeholder={t("optional, mehrere mit Komma")} value={cc} onChange={(e) => setCc(e.target.value)} /></div>
              <div className={row}><span className="text-xs text-slate-600">{t("Betreff")}</span><span>{pv.subject}</span></div>
              <div className={row}><span className="text-xs text-slate-600">{t("Anhang")}</span>
                <span className="flex flex-wrap gap-2">{pv.attachments.length ? pv.attachments.map((a: string) => <span key={a} className="inline-flex items-center gap-1 text-xs"><Paperclip className="h-3.5 w-3.5" />{a}</span>) : "–"}</span></div>
            </div>
            <pre className="max-h-40 overflow-y-auto whitespace-pre-wrap rounded bg-slate-50 p-2 font-sans text-xs text-slate-700">{pv.body}</pre>
            {blocking.length > 0 && <ul className="space-y-0.5 text-xs text-bad-text">{blocking.map((p: string) => <li key={p}>• {t(p)}</li>)}</ul>}
            <p className="flex items-start gap-1.5 rounded bg-warn-soft p-2 text-xs text-warn-text"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{t(pv.original_reminder)}</p>
            {err && <p className="text-xs text-bad-text">{err}</p>}
            <div className="flex justify-end gap-2 pt-1">
              <button className="btn" onClick={onClose} disabled={busy}>{t("Später")}</button>
              <button className="btn-primary" disabled={!canSend} onClick={send}><Send className="h-[18px] w-[18px]" /> {busy ? t("sendet …") : t("Jetzt senden")}</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
