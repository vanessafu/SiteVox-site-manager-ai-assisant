"use client";
import { useT } from "@/lib/i18n";
import { useParams } from "next/navigation";
import { useState } from "react";
import { api, dLong, time, useApi } from "@/lib/api";
import { Inbox, Paperclip, Trash2 } from "lucide-react";

export default function Mailbox() {
  const { pid } = useParams<{ pid: string }>();
  const { data, reload } = useApi<any[]>(`/api/projects/${pid}/mailbox`, 15_000);
  const [sel, setSel] = useState<any>(null);
  const { t } = useT();

  return (
    <div className="grid h-full grid-cols-1 md:grid-cols-[440px_minmax(0,1fr)]">
      <aside className="flex min-h-0 flex-col border-r border-slate-200 bg-white">
        <div className="space-y-3 border-b px-5 py-4">
          <h1 className="text-xl font-semibold">{t("Postfach")}</h1>
          <p className="text-xs leading-relaxed text-slate-500">{t("Dem Projekt zugeordnete E-Mails (Mock: .eml-Ordner, später Graph mit Mail.ReadWrite)")}</p>
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
    </div>
  );
}
