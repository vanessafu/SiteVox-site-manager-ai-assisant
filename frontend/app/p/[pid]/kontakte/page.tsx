"use client";
/**
 * Kontakte des Projekts: automatisch aus Stammdaten, Vertrag, Dokumenten und E-Mails erkannt (mit Fundstellen),
 * von der Bauleitung korrigierbar und ergänzbar. Im Sendedialog per Klick als Empfänger übernehmbar.
 */
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import { BadgeCheck, Ban, Building2, Mail, MapPin, Pencil, Phone, Plus, Search, Star, Trash2, User, X } from "lucide-react";
import { api, post, put, useApi } from "@/lib/api";
import { useT } from "@/lib/i18n";

const SRC: Record<string, string> = { master: "Stammdaten", contract: "Vertrag", document: "Dokument", email: "E-Mail" };
const EMPTY = { name: "", company: "", role: "", email: "", phone: "", address: "", authority: "", note: "" };

function ContactForm({ init, onClose, onSave }: { init: any; onClose: () => void; onSave: (d: any) => Promise<void> }) {
  const { t } = useT();
  const [f, setF] = useState<any>({ ...EMPTY, ...Object.fromEntries(Object.entries(init || {}).map(([k, v]) => [k, v ?? ""])) });
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const input = "mt-0.5 w-full rounded border px-2 py-1.5 text-sm text-slate-900";
  const field = (k: string, label: string, type = "text") => (
    <label className="block text-xs text-slate-600">{t(label)}
      <input className={input} type={type} value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></label>
  );
  const save = async () => {
    setBusy(true); setErr(null);
    try { await onSave(f); } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={() => !busy && onClose()}>
      <div className="w-full max-w-lg rounded-lg bg-white shadow-2xl" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <header className="flex items-center gap-2 border-b px-4 py-3">
          <User className="h-[18px] w-[18px]" /><h3 className="flex-1 font-semibold">{t(init?.id ? "Kontakt bearbeiten" : "Kontakt hinzufügen")}</h3>
          <button className="rounded p-1 hover:bg-slate-100" onClick={onClose} aria-label={t("Schließen")}><X className="h-[18px] w-[18px]" /></button>
        </header>
        <div className="grid gap-3 p-4 sm:grid-cols-2">
          {field("name", "Name")}{field("company", "Firma")}
          {field("role", "Funktion")}{field("email", "E-Mail", "email")}
          {field("phone", "Telefon")}
          <label className="block text-xs text-slate-600">{t("Vollmacht")}
            <select className={input} value={f.authority} onChange={(e) => setF({ ...f, authority: e.target.value })}>
              <option value="">{t("unbekannt")}</option>
              <option value="authorized">{t("bevollmächtigt (Anzeigen an diese Person)")}</option>
              <option value="not_authorized">{t("nicht bevollmächtigt")}</option>
            </select></label>
          <div className="sm:col-span-2">{field("address", "Adresse")}</div>
          <div className="sm:col-span-2">{field("note", "Notiz")}</div>
          {err && <p className="text-xs text-bad-text sm:col-span-2">{err}</p>}
        </div>
        <div className="flex justify-end gap-2 border-t px-4 py-3">
          <button className="btn" onClick={onClose} disabled={busy}>{t("Abbrechen")}</button>
          <button className="btn-primary" onClick={save} disabled={busy}>{t("Speichern")}</button>
        </div>
      </div>
    </div>
  );
}

export default function Kontakte() {
  const { pid } = useParams<{ pid: string }>();
  const { t } = useT();
  const { data, reload, error } = useApi<any[]>(`/api/projects/${pid}/contacts`);
  const [q, setQ] = useState("");
  const [edit, setEdit] = useState<any | null>(null);
  const list = useMemo(() => (data || []).filter((c) =>
    !q || [c.name, c.company, c.role, c.email, c.phone].some((x) => x?.toLowerCase().includes(q.toLowerCase()))), [data, q]);

  const remove = async (c: any) => {
    if (!window.confirm(t("„{x}“ aus den Kontakten entfernen?", { x: c.name || c.company || c.email }))) return;
    await api(`/api/projects/${pid}/contacts/${c.id}`, { method: "DELETE" });
    reload();
  };
  if (error) return <div className="p-6 text-sm text-bad-text">{error}</div>;

  return (
    <div className="mx-auto max-w-5xl space-y-3 px-4 py-4 lg:px-6">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="flex-1 text-xl font-semibold">{t("Kontakte")}</h1>
        <div className="relative">
          <Search className="absolute left-2 top-2 h-4 w-4 text-slate-400" />
          <input className="rounded border py-1.5 pl-8 pr-2 text-sm" placeholder={t("Suchen …")} value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <button className="btn" onClick={() => setEdit({})}><Plus className="h-4 w-4" /> {t("Kontakt hinzufügen")}</button>
      </div>
      <p className="text-sm text-slate-600">{t("Automatisch aus Vertrag, Unterlagen und E-Mails dieses Projekts erkannt – mit Fundstelle. Im Sendedialog per Klick als Empfänger übernehmen.")}</p>
      {!data && <p className="text-sm text-slate-500">{t("lädt …")}</p>}
      {data && !list.length && <p className="card p-4 text-sm text-slate-600">{t("Noch keine Kontakte erkannt – Vertrag oder E-Mails hochladen bzw. Postfach verbinden.")}</p>}
      <ul className="grid gap-2 md:grid-cols-2">
        {list.map((c) => (
          <li key={c.id} className={`card group space-y-1.5 p-3 ${c.recommended ? "ring-2 ring-ok" : ""}`}>
            <div className="flex items-start gap-2">
              {c.name ? <User className="mt-0.5 h-4 w-4 shrink-0 text-slate-500" /> : <Building2 className="mt-0.5 h-4 w-4 shrink-0 text-slate-500" />}
              <div className="min-w-0 flex-1">
                <div className="font-semibold leading-tight">{c.name || c.company || c.email}</div>
                {c.name && c.company && <div className="text-xs text-slate-600">{c.company}</div>}
                {c.role && <div className="text-xs text-slate-600">{t(c.role)}</div>}
              </div>
              <span className="flex opacity-60 group-hover:opacity-100">
                <button className="rounded p-1 text-slate-400 hover:text-accent-text" onClick={() => setEdit(c)} title={t("Bearbeiten")}><Pencil className="h-3.5 w-3.5" /></button>
                <button className="rounded p-1 text-slate-400 hover:text-bad" onClick={() => remove(c)} title={t("Entfernen")}><Trash2 className="h-3.5 w-3.5" /></button>
              </span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {c.recommended && <span className="pill bg-ok-soft text-ok-text"><Star className="h-3 w-3" /> {t("Empfänger für Anzeigen")}</span>}
              {c.authority === "authorized" && <span className="pill bg-ok-soft text-ok-text"><BadgeCheck className="h-3 w-3" /> {t("bevollmächtigt")}</span>}
              {c.authority === "not_authorized" && <span className="pill bg-warn-soft text-warn-text"><Ban className="h-3 w-3" /> {t("nicht bevollmächtigt")}</span>}
              {c.manual && <span className="pill bg-slate-100 text-slate-600">{t("manuell")}</span>}
            </div>
            <div className="space-y-0.5 text-sm">
              {c.email && <a className="flex items-center gap-1.5 text-accent-text hover:underline" href={`mailto:${c.email}`}><Mail className="h-3.5 w-3.5" />{c.email}</a>}
              {c.phone && <a className="flex items-center gap-1.5 hover:underline" href={`tel:${c.phone.replace(/[^\d+]/g, "")}`}><Phone className="h-3.5 w-3.5" />{c.phone}</a>}
              {c.address && <div className="flex items-center gap-1.5 text-slate-700"><MapPin className="h-3.5 w-3.5" />{c.address}</div>}
              {c.note && <div className="text-xs italic text-slate-600">{c.note}</div>}
            </div>
            {c.sources?.length > 0 && (
              <details className="text-xs text-slate-600">
                <summary className="cursor-pointer">{t("Fundstellen")} ({c.sources.length}): {Array.from(new Set(c.sources.map((s: any) => t(SRC[s.source] || s.source)))).join(", ")}</summary>
                <ul className="mt-1 space-y-1">
                  {c.sources.map((s: any, i: number) => (
                    <li key={i} className="rounded bg-slate-50 p-1.5">
                      <div className="font-medium">{t(SRC[s.source] || s.source)} · {s.title}{s.page ? ` · S. ${s.page}` : ""}</div>
                      {s.quote && <div className="italic">„{s.quote}“</div>}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </li>
        ))}
      </ul>
      {edit && <ContactForm init={edit} onClose={() => setEdit(null)} onSave={async (d) => {
        if (edit.id) await put(`/api/projects/${pid}/contacts/${edit.id}`, d); else await post(`/api/projects/${pid}/contacts`, d);
        setEdit(null); reload();
      }} />}
    </div>
  );
}
