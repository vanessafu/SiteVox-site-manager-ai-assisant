"use client";
import { useT } from "@/lib/i18n";
import { useParams } from "next/navigation";
import { useState } from "react";
import { api, dLong, time, useApi } from "@/lib/api";
import { Trash2 } from "lucide-react";

export default function Mailbox() {
  const { pid } = useParams<{ pid: string }>();
  const { data, reload } = useApi<any[]>(`/api/projects/${pid}/mailbox`, 15_000);
  const [sel, setSel] = useState<any>(null);
  const { t } = useT();
  return (
    <div className="grid h-full grid-cols-1 md:grid-cols-[320px_minmax(0,1fr)]">
      <ul className="overflow-y-auto border-r border-slate-200 bg-white">
        <li className="border-b px-3 py-2 text-xs text-slate-600">{t("Dem Projekt zugeordnete E-Mails (Mock: .eml-Ordner, später Graph mit Mail.ReadWrite)")}</li>
        {(data || []).map((m) => (
          <li key={m.message_id}>
            <button onClick={() => setSel(m)} className={`w-full border-b px-3 py-2 text-left hover:bg-slate-50 ${sel?.message_id === m.message_id ? "bg-slate-100" : ""}`}>
              <div className="flex justify-between text-xs"><span className="truncate font-medium">{m.from.split("<")[0]}</span><span className="text-slate-500">{time(m.received_at)}</span></div>
              <div className="truncate text-sm">{m.subject}</div>
              <div className="truncate text-2xs text-slate-600">{m.summary}</div>
            </button>
          </li>
        ))}
      </ul>
      <div className="overflow-y-auto p-4">
        {sel ? (
          <div className="card space-y-2 p-4">
            <div className="flex items-start gap-2"><h2 className="flex-1 font-semibold">{sel.subject}</h2>
              {sel.capture_id && <button className="btn-xs text-bad-text" onClick={async () => {
                if (!window.confirm(t("„{x}“ löschen? Abgeleitete Mengen, Belege und Ereignisse werden mit entfernt (Audit-Log).", { x: sel.subject }))) return;
                try { await api(`/api/captures/${sel.capture_id}`, { method: "DELETE" }); setSel(null); reload(); } catch (e: any) { window.alert(e.message); }
              }}><Trash2 className="h-3.5 w-3.5" /> {t("Löschen")}</button>}</div>
            <div className="text-xs text-slate-600">{t("Von {f} · An {t}", { f: sel.from, t: sel.to })}{sel.cc && ` · Cc ${sel.cc}`} · {dLong(sel.received_at)} {time(sel.received_at)}</div>
            {sel.summary && <div className="rounded bg-accent-soft p-2 text-xs text-accent-text">{t("KI-Zusammenfassung")}: {sel.summary}</div>}
            {sel.event_ids?.length > 0 && <div className="text-xs">{t("Verknüpfte Ereignisse")}: {sel.event_ids.join(", ")}</div>}
            <pre className="whitespace-pre-wrap font-sans text-sm">{sel.body}</pre>
          </div>
        ) : <p className="text-sm text-slate-500">{t("E-Mail auswählen")}</p>}
      </div>
    </div>
  );
}
