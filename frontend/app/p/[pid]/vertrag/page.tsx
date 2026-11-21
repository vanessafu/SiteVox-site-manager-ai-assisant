"use client";
import { useT } from "@/lib/i18n";
import { useParams } from "next/navigation";
import { useState } from "react";
import { api, useApi } from "@/lib/api";
import { ArrowLeft, Download, FileText, Scale, Search, Trash2, Upload } from "lucide-react";

const GAEB_ACCEPT = ".x31,.x80,.x81,.x82,.x83,.x84,.x85,.x86,.x87,.x88,.x89,.d81,.d82,.d83,.d84,.d85,.d86,.p81,.p82,.p83,.p84,.p85,.p86";
const GAEB_PHASES: [string, string][] = [
  ["83", "X83 · Angebotsaufforderung"], ["84", "X84 · Angebotsabgabe"], ["86", "X86 · Auftragserteilung"], ["81", "X81 · Leistungsbeschreibung"],
];

/** Wissensbasis: Rechtsgrundlagen + Projektunterlagen (Vertrag, LV inkl. GAEB, Pläne, Protokolle …) mit Suche. */
export default function Knowledge() {
  const { pid } = useParams<{ pid: string }>();
  const { data: docs, reload } = useApi<any[]>(`/api/projects/${pid}/knowledge`);
  const [docType, setDocType] = useState("lv");
  const [upMsg, setUpMsg] = useState<string | null>(null);
  const [doc, setDoc] = useState<any>(null);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<any[] | null>(null);
  const [phase, setPhase] = useState("83");
  const { t } = useT();
  const upload = async (f: File) => {
    const fd = new FormData();
    fd.append("kind", "document");
    fd.append("file", f, f.name);
    fd.append("doc_type", /\.(x\d\d|d8\d|p8\d)$/i.test(f.name) ? "lv" : docType);
    fd.append("doc_title", f.name.replace(/\.[^.]+$/, ""));
    setUpMsg(t("Übertragen – wird ausgewertet"));
    await api(`/api/projects/${pid}/captures`, { method: "POST", body: fd });
    setTimeout(() => { reload(); setUpMsg(null); }, 3000);
  };
  const removeDoc = async (d: any) => {
    if (!window.confirm(t("„{x}“ löschen?", { x: d.title }))) return;
    try { await api(`/api/documents/${d.doc_id}`, { method: "DELETE" }); setDoc(null); reload(); } catch (e: any) { window.alert(e.message); }
  };
  const search = async () => { if (q.trim()) { setDoc(null); setHits(await api(`/api/projects/${pid}/knowledge/search?q=${encodeURIComponent(q)}`)); } };
  const home = () => { setDoc(null); setHits(null); };
  const open = async (d: any) => { setHits(null); setDoc(await api(`/api/documents/${d.doc_id}`)); };
  const gaebReady = doc?.gaeb_exportable;

  return (
    <div className="grid gap-6 px-6 py-5 lg:grid-cols-[400px_minmax(0,1fr)] xl:gap-8">
      <aside className="space-y-6">
        <div>
          <h1 className="text-xl font-semibold">{t("Wissensbasis")}</h1>
          <p className="mt-1 text-sm leading-relaxed text-slate-600">{t("Unterlagen, auf die sich Schreiben und Prüfungen stützen.")}</p>
        </div>
        {(["legal", "project"] as const).map((col) => {
          const list = (docs || []).filter((d) => d.collection === col);
          return (
            <section key={col}>
              <div className="mb-2 flex items-center gap-1.5 text-2xs font-medium uppercase tracking-wide text-slate-500">
                {col === "legal" ? <Scale className="h-3.5 w-3.5" /> : <FileText className="h-3.5 w-3.5" />}
                {t(col === "legal" ? "Rechtsgrundlagen (VOB/B aktuelle Fassung)" : "Projektunterlagen")} · {list.length}
              </div>
              <ul className="space-y-1">{list.map((d) => (
                <li key={d.doc_id} className={`group flex items-center rounded-md ${doc?.doc_id === d.doc_id ? "bg-white shadow-sm ring-1 ring-slate-200" : "hover:bg-white"}`}>
                  <button onClick={() => open(d)} className="min-w-0 flex-1 px-3 py-2.5 text-left">
                    <div className="text-[15px] leading-snug">{d.title}</div>
                    <div className="mt-0.5 flex items-center gap-1.5 text-xs text-slate-500">
                      {t("{n} S.", { n: d.pages })}
                      {d.format === "gaeb" && <span className="pill bg-accent-soft text-accent-text">GAEB</span>}
                    </div>
                  </button>
                  {col === "project" && <button onClick={() => removeDoc(d)} className="mr-2 rounded p-1.5 text-slate-400 opacity-60 hover:text-bad group-hover:opacity-100" aria-label={t("Löschen")}><Trash2 className="h-4 w-4" /></button>}
                </li>
              ))}</ul>
            </section>
          );
        })}
        <div className="card space-y-3 p-4">
          <div className="text-sm font-medium">{t("Dokument hochladen")}</div>
          <select className="w-full rounded-md border px-3 py-2 text-sm" value={docType} onChange={(e) => setDocType(e.target.value)}>
            {[["lv", "Leistungsverzeichnis (LV)"], ["vertrag", "Vertrag"], ["planlieferliste", "Planlieferliste"], ["protokoll", "Protokoll"], ["dokument", "Sonstiges"]].map(([v, l]) => <option key={v} value={v}>{t(l)}</option>)}
          </select>
          <label className="btn w-full cursor-pointer justify-center py-2"><Upload className="h-4 w-4" /> {t("PDF / DOCX / GAEB / Bild wählen")}
            <input type="file" className="hidden" accept={`.pdf,.docx,.doc,.md,.txt,image/*,${GAEB_ACCEPT}`} onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = ""; }} /></label>
          {upMsg && <p className="text-xs text-slate-600">{upMsg}</p>}
          <p className="text-xs leading-relaxed text-slate-500">{t("GAEB: DA XML (.x81–.x89), GAEB 2000 (.p8x) und GAEB 90 (.d8x) werden als LV mit Positionen eingelesen.")}</p>
        </div>
        <p className="text-xs leading-relaxed text-slate-500">{t("Normzitate in Schreiben stammen ausschließlich aus den Vorlagen. Die Wissensbasis dient dem Nachweis und der Suche (BM25 + BGE-M3, Rerank).")}</p>
      </aside>

      <main className="min-w-0 space-y-4">
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input className="w-full rounded-md border py-2 pl-9 pr-3 text-sm" placeholder={t("z. B. Behinderung unverzüglich schriftlich")} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search()} />
          </div>
          <button className="btn" onClick={search}>{t("Suchen")}</button>
        </div>
        {hits && (
          <button onClick={home} className="inline-flex items-center gap-1 text-sm text-slate-600 hover:text-slate-900"><ArrowLeft className="h-4 w-4" /> {t("Suche schließen")}</button>
        )}
        {hits && (hits.length ? <div className="space-y-3">{hits.map((h) => (
          <div key={h.chunk_id} className="card p-4 text-sm"><div className="mb-1.5 flex flex-wrap justify-between gap-2 text-xs"><b className="text-sm">{h.title}</b><span className="text-slate-500">{h.doc_title} · {t("S. {n}", { n: h.page })} · {t("Relevanz")} {Number(h.relevance).toFixed(2)}</span></div><p className="whitespace-pre-wrap leading-relaxed text-slate-700">{h.text.slice(0, 600)}</p></div>
        ))}</div> : <p className="text-sm text-slate-500">{t("Keine Treffer")}</p>)}
        {doc && !hits && (
          <div className="card space-y-4 p-5">
            <div className="flex flex-wrap items-start gap-3">
              <h2 className="flex-1 text-lg font-semibold">{doc.title}</h2>
              {gaebReady && (
                <div className="flex items-center gap-2">
                  <select className="rounded-md border px-2 py-1.5 text-sm" value={phase} onChange={(e) => setPhase(e.target.value)} title={t("GAEB-Austauschphase")}>
                    {GAEB_PHASES.map(([v, l]) => <option key={v} value={v}>{t(l)}</option>)}
                  </select>
                  <a className="btn" href={`/api/documents/${doc.doc_id}/gaeb?phase=${phase}`}><Download className="h-4 w-4" /> {t("GAEB-Export")}</a>
                </div>
              )}
            </div>
            {doc.gaeb && <p className="text-xs text-slate-600">{t("GAEB {v} · Phase {p} · {n} Positionen", { v: doc.gaeb.format, p: doc.gaeb.phase || "–", n: doc.gaeb.positions })}</p>}
            {doc.pages.map((p: any) => <div key={p.page}><div className="mb-1 text-2xs text-slate-500">{t("Seite {n}", { n: p.page })}</div><pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed">{p.text}</pre></div>)}
          </div>
        )}
        {!doc && !hits && (
          <div className="flex min-h-[50vh] flex-col items-center justify-center gap-2 text-slate-400">
            <FileText className="h-10 w-10" />
            <p className="text-sm">{t("Dokument links auswählen oder oben suchen")}</p>
          </div>
        )}
      </main>
    </div>
  );
}
