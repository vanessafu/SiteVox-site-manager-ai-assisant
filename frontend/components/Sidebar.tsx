"use client";
import Link from "next/link";
import { useState } from "react";
import { useParams, usePathname, useRouter } from "next/navigation";
import { BookOpen, Contact, FileDown, FileUp, FileWarning, History, LayoutDashboard, Mail, Pencil, Plus, Smartphone, Timer, Trash2, X } from "lucide-react";
import { api, post, useApi } from "@/lib/api";
import { LangToggle, useT } from "@/lib/i18n";

const NAV = [
  { href: "", label: "Dashboard", icon: LayoutDashboard },
  { href: "/erfassungen", label: "Erfassungen", icon: Timer },
  { href: "/schreiben", label: "Schreiben", icon: FileWarning },
  { href: "/postfach", label: "Postfach", icon: Mail },
  { href: "/kontakte", label: "Kontakte", icon: Contact },
  { href: "/vertrag", label: "Wissensbasis", icon: BookOpen },
  { href: "/export", label: "Export", icon: FileDown },
];

const GAEB = /\.(x\d\d|d8\d|p8\d)$/i;
const DOC_TYPES: [string, string][] = [
  ["vertrag", "Vertrag"], ["lv", "Leistungsverzeichnis (LV)"], ["bauzeitenplan", "Bauzeitenplan (Excel)"],
  ["planlieferliste", "Planlieferliste"], ["protokoll", "Protokoll"], ["dokument", "Sonstiges"],
];
/** Dokumentart aus dem Dateinamen raten – im Dialog änderbar */
const guessType = (n: string) =>
  GAEB.test(n) ? "lv"
    : /bauzeit|terminplan|zeitplan|schedule/i.test(n) && /\.(xlsx|xlsm|csv)$/i.test(n) ? "bauzeitenplan"
    : /vertrag|contract/i.test(n) ? "vertrag"
    : /(^|[^a-z])lv([^a-z]|$)|leistungsverz/i.test(n) ? "lv"
    : /planliefer/i.test(n) ? "planlieferliste"
    : /protokoll/i.test(n) ? "protokoll" : "dokument";

/** Dialog „Neues Projekt“: Stammdaten + Unterlagen (Vertrag, LV, Bauzeitenplan …) gleich beim Anlegen hochladen. */
function NewProject({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const { t } = useT();
  const [f, setF] = useState({ name: "", title: "", address: "", coords: "", contract_no: "", contract_date: "",
    client_name: "", client_address: "", client_representative: "", client_email: "" });
  const [files, setFiles] = useState<{ file: File; type: string; state?: string }[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const add = (list: FileList | null) =>
    list && setFiles((x) => [...x, ...Array.from(list).filter((n) => !x.some((y) => y.file.name === n.name))
      .map((file) => ({ file, type: guessType(file.name) }))]);
  const mark = (i: number, state: string) => setFiles((x) => x.map((y, j) => (j === i ? { ...y, state } : y)));

  const save = async () => {
    setBusy(true); setErr(null);
    let id: string;
    try { id = (await post(`/api/projects`, f)).id; } catch (e: any) { setErr(e.message); setBusy(false); return; }
    let failed = 0;
    for (const [i, x] of files.entries()) {
      mark(i, "…");
      const fd = new FormData();
      fd.append("file", x.file, x.file.name);
      try {
        if (x.type === "bauzeitenplan") await api(`/api/projects/${id}/schedule-import`, { method: "POST", body: fd });
        else {
          fd.append("kind", "document"); fd.append("doc_type", x.type); fd.append("doc_title", x.file.name.replace(/\.[^.]+$/, ""));
          await api(`/api/projects/${id}/captures`, { method: "POST", body: fd });
        }
        mark(i, "ok");
      } catch (e: any) { mark(i, e.message); failed++; }
    }
    setBusy(false);
    if (!failed) return onCreated(id);
    setErr(t("Projekt angelegt, {n} Datei(en) nicht übernommen – später unter Wissensbasis erneut hochladen.", { n: failed }));
    setTimeout(() => onCreated(id), 5000);
  };

  const input = "mt-0.5 w-full rounded border px-2 py-1.5 text-sm text-slate-900";
  const field = (k: keyof typeof f, label: string, ph = "", type = "text") => (
    <label className="block text-xs text-slate-600">{t(label)}
      <input className={input} type={type} value={f[k]} placeholder={ph} autoFocus={k === "name"} onChange={(e) => setF({ ...f, [k]: e.target.value })} />
    </label>
  );
  const head = "text-xs font-semibold uppercase tracking-wide text-slate-500";
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={() => !busy && onClose()}>
      <div className="flex max-h-[92vh] w-full max-w-2xl flex-col rounded-lg bg-white shadow-2xl" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <header className="flex items-center gap-2 border-b px-4 py-3">
          <Plus className="h-[18px] w-[18px]" /><h3 className="flex-1 font-semibold">{t("Neues Projekt")}</h3>
          <button className="rounded p-1 hover:bg-slate-100" onClick={onClose} disabled={busy} aria-label={t("Schließen")}><X className="h-[18px] w-[18px]" /></button>
        </header>
        <div className="space-y-4 overflow-y-auto p-4">
          <div className="grid gap-3 sm:grid-cols-2">
            {field("name", "Kurzname *", "BV Musterstraße")}
            {field("title", "Bauvorhaben", "Neubau …")}
            <div className="sm:col-span-2">{field("address", "Adresse Baustelle")}</div>
            <div className="sm:col-span-2">{field("coords", "Koordinaten Baustelle (Breite, Länge) – für das Wetter", "48.1305, 11.6955")}
              <p className="mt-0.5 text-2xs text-slate-500">{t("In Google Maps: Rechtsklick auf die Baustelle → erste Zeile (Koordinaten) anklicken = kopiert.")}</p></div>
            {field("contract_no", "Vertragsnummer")}
            {field("contract_date", "Vertragsdatum", "", "date")}
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className={`${head} sm:col-span-2`}>{t("Auftraggeber")}</div>
            {field("client_name", "Auftraggeber")}
            {field("client_representative", "Bevollmächtigter Vertreter")}
            {field("client_email", "E-Mail AG (Empfänger der Anzeigen)", "vorname.name@auftraggeber.de", "email")}
            {field("client_address", "Adresse AG")}
            <p className="text-2xs text-slate-500 sm:col-span-2">{t("Leer lassen, was im Vertrag steht – nach dem Hochladen des Vertrags füllt SiteVox leere Felder automatisch (mit Fundstelle).")}</p>
          </div>
          <div className="space-y-2">
            <div className={head}>{t("Unterlagen")}</div>
            <label className="flex cursor-pointer flex-col items-center gap-1 rounded-md border-2 border-dashed border-slate-300 p-4 text-center text-sm text-slate-600 hover:bg-slate-50"
              onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); add(e.dataTransfer.files); }}>
              <FileUp className="h-5 w-5" />
              {t("Vertrag, LV (auch GAEB), Bauzeitenplan (Excel), Protokolle … hierher ziehen oder auswählen")}
              <input type="file" multiple className="hidden" onChange={(e) => { add(e.target.files); e.target.value = ""; }}
                accept=".pdf,.docx,.doc,.md,.txt,.xlsx,.xlsm,.csv,image/*,.x81,.x82,.x83,.x84,.x85,.x86,.d83,.d84,.d86,.p83,.p84,.p86" />
            </label>
            {files.length > 0 && (
              <ul className="divide-y divide-slate-100 rounded border text-sm">
                {files.map((x, i) => (
                  <li key={x.file.name} className="flex items-center gap-2 px-2 py-1.5">
                    <span className="min-w-0 flex-1 truncate" title={x.file.name}>{x.file.name}</span>
                    <select className="rounded border px-1.5 py-0.5 text-xs" value={x.type} disabled={busy}
                      onChange={(e) => setFiles((l) => l.map((y, j) => (j === i ? { ...y, type: e.target.value } : y)))}>
                      {DOC_TYPES.map(([v, l]) => <option key={v} value={v}>{t(l)}</option>)}
                    </select>
                    {x.state === "ok" ? <span className="text-xs text-ok-text">✓</span>
                      : x.state === "…" ? <span className="text-xs text-slate-500">…</span>
                      : x.state ? <span className="max-w-[10rem] truncate text-xs text-bad-text" title={x.state}>{x.state}</span>
                      : <button className="rounded p-0.5 text-slate-400 hover:text-bad" disabled={busy}
                          onClick={() => setFiles((l) => l.filter((_, j) => j !== i))} aria-label={t("Löschen")}><X className="h-3.5 w-3.5" /></button>}
                  </li>
                ))}
              </ul>
            )}
            <p className="text-2xs text-slate-600">{t("Dokumente landen in der Wissensbasis und werden im Hintergrund ausgewertet; der Bauzeitenplan liefert die Vorgänge für Dashboard und Bericht.")}</p>
          </div>
          {err && <p className="text-xs text-bad-text">{err}</p>}
        </div>
        <div className="flex justify-end gap-2 border-t px-4 py-3">
          <button className="btn" onClick={onClose} disabled={busy}>{t("Abbrechen")}</button>
          <button className="btn-primary" onClick={save} disabled={!f.name.trim() || busy}>
            <Plus className="h-[18px] w-[18px]" /> {busy ? t("wird angelegt …") : t("Anlegen")}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function Sidebar() {
  const { pid } = useParams<{ pid: string }>();
  const path = usePathname();
  const router = useRouter();
  const { t } = useT();
  const { data: projects, reload } = useApi<any[]>("/api/projects", 15_000);
  const [adding, setAdding] = useState(false);

  const remove = async (p: any) => {
    if (!window.confirm(t("Projekt „{n}“ mit allen Erfassungen, Ereignissen und Schreiben löschen? Das kann nicht rückgängig gemacht werden.", { n: p.name }))) return;
    try {
      await api(`/api/projects/${p.id}`, { method: "DELETE" });
      const rest = (projects || []).filter((x) => x.id !== p.id);
      await reload();
      if (p.id === pid) router.push(rest.length ? `/p/${rest[0].id}` : "/");
    } catch (e: any) { window.alert(e.message); }
  };

  return (
    <nav className="flex h-full w-64 shrink-0 flex-col border-r border-slate-200 bg-white px-4 py-4 text-base max-md:w-14 max-md:px-1.5">
      <div className="mb-4 flex items-center gap-2 px-1 text-lg font-semibold">
        <img src="/icon.svg" alt="" className="h-7 w-7" /> <span className="max-md:hidden">SiteVox</span>
        <span className="ml-auto max-md:hidden"><LangToggle /></span>
      </div>
      <div className="mb-1 flex items-center px-1 text-xs uppercase tracking-wide text-slate-500 max-md:justify-center">
        <span className="max-md:hidden">{t("Projekte")}</span>
        <button className="ml-auto rounded p-1 text-slate-600 hover:bg-slate-100 max-md:ml-0" title={t("Neues Projekt")} onClick={() => setAdding(true)}>
          <Plus className="h-4 w-4" />
        </button>
      </div>
      <ul className="space-y-0.5">
        {(projects || []).sort((a, b) => b.badge - a.badge || a.name.localeCompare(b.name)).map((p) => (
          <li key={p.id} className="group relative">
            <Link href={`/p/${p.id}`} title={`${p.title} · ${t("{n} fristgebundene Schreiben offen", { n: p.badge })}`}
              className={`flex items-center justify-between rounded-md px-3 py-2 pr-14 max-md:pr-3 ${p.id === pid ? "bg-slate-100 font-medium" : "text-slate-600 hover:bg-slate-50"}`}>
              <span className="truncate max-md:text-2xs">{p.name}</span>
              {p.badge > 0 && <span className="ml-1 rounded-full bg-bad px-1.5 text-2xs font-semibold text-white">{p.badge}</span>}
            </Link>
            <span className="absolute right-1 top-1/2 flex -translate-y-1/2 opacity-0 focus-within:opacity-100 group-hover:opacity-100 max-md:hidden">
              <Link href={`/p/${p.id}/projekt`} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-accent-text" title={t("Projekt bearbeiten")}>
                <Pencil className="h-3.5 w-3.5" />
              </Link>
              <button className="rounded p-1 text-slate-400 hover:bg-bad-soft hover:text-bad-text" title={t("Projekt löschen")} onClick={() => remove(p)}>
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </span>
          </li>
        ))}
      </ul>
      <div className="my-3 border-t border-slate-200" />
      <ul className="space-y-0.5">
        {NAV.map(({ href, label, icon: Icon }) => {
          const full = `/p/${pid}${href}`;
          const active = href === "" ? path === full : path.startsWith(full);
          return (
            <li key={href}>
              <Link href={full} title={t(label)}
                className={`flex items-center gap-3 rounded-md px-3 py-2 ${active ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-50"}`}>
                <Icon className="h-5 w-5 shrink-0" /> <span className="max-md:hidden">{t(label)}</span>
              </Link>
            </li>
          );
        })}
      </ul>
      <div className="mt-auto border-t border-slate-200 pt-3">
        <Link href={`/p/${pid}/verlauf`} title={t("Verlauf")}
          className={`flex items-center gap-3 rounded-md px-3 py-2 ${path.startsWith(`/p/${pid}/verlauf`) ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-50"}`}>
          <History className="h-5 w-5 shrink-0" /> <span className="max-md:hidden">{t("Verlauf")}</span>
        </Link>
      </div>
      <Link href={`/m/${pid}`} className="flex items-center gap-3 rounded-md px-3 py-2 text-sm text-slate-600 hover:bg-slate-50" title={t("Baustellen-Modus")}>
        <Smartphone className="h-5 w-5" /> <span className="max-md:hidden">{t("Baustellen-Modus")}</span>
      </Link>
      {adding && <NewProject onClose={() => setAdding(false)} onCreated={(id) => { setAdding(false); reload(); router.push(`/p/${id}`); }} />}
    </nav>
  );
}
