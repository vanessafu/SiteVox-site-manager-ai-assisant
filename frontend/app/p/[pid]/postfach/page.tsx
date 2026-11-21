"use client";
import { useT } from "@/lib/i18n";
import { useParams } from "next/navigation";
import { useState } from "react";
import { api, dLong, post, time, useApi } from "@/lib/api";
import { Inbox, KeyRound, Paperclip, Plus, RefreshCw, Trash2 } from "lucide-react";
import MailConnect from "@/components/MailConnect";

export default function Mailbox() {
  const { pid } = useParams<{ pid: string }>();
  const { data, reload } = useApi<any[]>(`/api/projects/${pid}/mailbox`, 15_000);
  const { data: accounts, reload: reloadAcc } = useApi<any[]>(`/api/projects/${pid}/mail-accounts`, 30_000);
  const [sel, setSel] = useState<any>(null);
  const [connect, setConnect] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const { t } = useT();

  const sync = async (a: any) => {
    setBusy(a.account_id); setMsg(null);
    try {
      const r = await post(`/api/projects/${pid}/mail-accounts/${a.account_id}/sync`);
      setMsg(t("{n} neue E-Mail(s) übernommen · {d} bereits vorhanden · {o} anderes Projekt", { n: r.new, d: r.duplicate, o: r.other_project }));
      setTimeout(reload, 2500);
    } catch (e: any) {
      if (e.status === 409) return unlock(a);
      setMsg(e.message);
    } finally { setBusy(null); reloadAcc(); }
  };
  const unlock = async (a: any) => {
    const pw = window.prompt(t("App-Passwort für {a} eingeben (wird nicht gespeichert):", { a: a.address }));
    if (!pw) return;
    try { await post(`/api/projects/${pid}/mail-accounts/${a.account_id}/unlock`, { password: pw }); reloadAcc();
      setMsg(t("Entsperrt – E-Mails werden jetzt im Hintergrund abgerufen."));
      setTimeout(() => { reload(); reloadAcc(); }, 6000); }
    catch (e: any) { setMsg(e.message); }
  };
  const remove = async (a: any) => {
    if (!window.confirm(t("Verbindung zu {a} trennen? Bereits übernommene E-Mails bleiben erhalten.", { a: a.address }))) return;
    await api(`/api/projects/${pid}/mail-accounts/${a.account_id}`, { method: "DELETE" });
    reloadAcc();
  };

  return (
    <div className="grid h-full grid-cols-1 md:grid-cols-[440px_minmax(0,1fr)]">
      <aside className="flex min-h-0 flex-col border-r border-slate-200 bg-white">
        <div className="space-y-3 border-b px-5 py-4">
          <div className="flex items-center gap-2">
            <h1 className="flex-1 text-xl font-semibold">{t("Postfach")}</h1>
            <button className="btn" onClick={() => setConnect(true)}><Plus className="h-4 w-4" /> {t("Postfach verbinden")}</button>
          </div>
          {(accounts || []).map((a) => (
            <div key={a.account_id} className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm">
              <span className={`h-2 w-2 shrink-0 rounded-full ${a.connected ? "bg-ok" : "bg-slate-300"}`} title={t(a.connected ? "verbunden" : "Passwort erforderlich")} />
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium">{a.address}</div>
                <div className="text-2xs text-slate-500">{a.imap_host} · {a.folder}{a.last_sync ? ` · ${t("zuletzt")} ${dLong(a.last_sync)} ${time(a.last_sync)}` : ""}</div>
                <div className={`text-2xs ${a.connected ? "text-ok-text" : "text-warn-text"}`}>
                  {!a.connected ? t("Gesperrt – Passwort eingeben, dann wird automatisch abgerufen")
                    : a.auto_sync_min ? t("Automatischer Abruf alle {n} Min.", { n: a.auto_sync_min }) + (a.next_sync ? ` · ${t("nächster")} ${time(a.next_sync)}` : "")
                    : t("Automatischer Abruf aus")}
                </div>
                {a.last_result?.error && <div className="text-2xs text-bad-text" title={a.last_result.error}>{t("Letzter Abruf fehlgeschlagen")}: {a.last_result.error}</div>}
              </div>
              {a.connected
                ? <button className="btn-xs" disabled={busy === a.account_id} onClick={() => sync(a)}><RefreshCw className={`h-3.5 w-3.5 ${busy === a.account_id ? "animate-spin" : ""}`} /> {t("Abrufen")}</button>
                : <button className="btn-xs" onClick={() => unlock(a)}><KeyRound className="h-3.5 w-3.5" /> {t("Passwort")}</button>}
              <button className="rounded p-1 text-slate-400 hover:text-bad" onClick={() => remove(a)} aria-label={t("Trennen")}><Trash2 className="h-4 w-4" /></button>
            </div>
          ))}
          {msg && <p className="text-xs text-slate-600">{msg}</p>}
          {!accounts?.length && <p className="text-xs leading-relaxed text-slate-500">{t("Dem Projekt zugeordnete E-Mails (Mock: .eml-Ordner, später Graph mit Mail.ReadWrite)")}</p>}
        </div>
        <ul className="min-h-0 flex-1 overflow-y-auto">
          {(data || []).map((m) => (
            <li key={m.message_id}>
              <button onClick={() => setSel(m)} className={`w-full border-b px-5 py-3.5 text-left hover:bg-slate-50 ${sel?.message_id === m.message_id ? "bg-slate-100" : ""}`}>
                <div className="flex items-baseline justify-between gap-3 text-sm"><span className="truncate font-medium">{m.from.split("<")[0]}</span><span className="shrink-0 text-xs text-slate-500">{time(m.received_at)}</span></div>
                <div className="mt-0.5 line-clamp-2 text-[15px] leading-snug">{m.subject}</div>
                {m.summary && <div className="mt-1 line-clamp-2 text-xs leading-relaxed text-slate-600">{m.summary}</div>}
              </button>
            </li>
          ))}
        </ul>
      </aside>
      <div className="overflow-y-auto px-6 py-5">
        {sel ? (
          <div className="card space-y-3 p-5">
            <div className="flex items-start gap-2"><h2 className="flex-1 text-lg font-semibold">{sel.subject}</h2>
              {sel.capture_id && <button className="btn-xs text-bad-text" onClick={async () => {
                if (!window.confirm(t("„{x}“ löschen? Abgeleitete Mengen, Belege und Ereignisse werden mit entfernt (Audit-Log).", { x: sel.subject }))) return;
                try { await api(`/api/captures/${sel.capture_id}`, { method: "DELETE" }); setSel(null); reload(); } catch (e: any) { window.alert(e.message); }
              }}><Trash2 className="h-3.5 w-3.5" /> {t("Löschen")}</button>}</div>
            <div className="text-sm text-slate-600">{t("Von {f} · An {t}", { f: sel.from, t: sel.to })}{sel.cc && ` · Cc ${sel.cc}`} · {dLong(sel.received_at)} {time(sel.received_at)}</div>
            {sel.attachments?.length > 0 && <div className="flex flex-wrap items-center gap-1.5 text-xs text-slate-600"><Paperclip className="h-3.5 w-3.5" />{sel.attachments.join(", ")}</div>}
            {sel.summary && <div className="rounded-md bg-accent-soft p-3 text-sm text-accent-text">{t("KI-Zusammenfassung")}: {sel.summary}</div>}
            {sel.event_ids?.length > 0 && <div className="text-sm">{t("Verknüpfte Ereignisse")}: {sel.event_ids.join(", ")}</div>}
            <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed">{sel.body}</pre>
          </div>
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-slate-400">
            <Inbox className="h-10 w-10" />
            <p className="text-sm">{t("E-Mail auswählen")}</p>
          </div>
        )}
      </div>
      {connect && <MailConnect pid={pid} onClose={() => setConnect(false)} onDone={(a) => { setConnect(false); reloadAcc(); sync(a); }} />}
    </div>
  );
}
