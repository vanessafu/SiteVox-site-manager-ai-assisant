"use client";
import { useT } from "@/lib/i18n";
import { useParams } from "next/navigation";
import { useState } from "react";
import { api, useApi } from "@/lib/api";
import { Trash2, Upload } from "lucide-react";

/** Wissensbasis: zeigt, auf welche Unterlagen sich die KI stützt (Recht + Projekt), mit Suche. */
export default function Knowledge() {
  const { pid } = useParams<{ pid: string }>();
  const { data: docs, reload } = useApi<any[]>(`/api/projects/${pid}/knowledge`);
  const [docType, setDocType] = useState("lv");
  const [upMsg, setUpMsg] = useState<string | null>(null);
  const [doc, setDoc] = useState<any>(null);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<any[] | null>(null);
  const { t } = useT();
  const upload = async (f: File) => {
    const fd = new FormData();
    fd.append("kind", "document");
    fd.append("file", f, f.name);
    fd.append("doc_type", docType);
    fd.append("doc_title", f.name.replace(/\.[^.]+$/, ""));
    setUpMsg(t("Übertragen – wird ausgewertet"));
    await api(`/api/projects/${pid}/captures`, { method: "POST", body: fd });
    setTimeout(() => { reload(); setUpMsg(null); }, 2500);
  };
  const removeDoc = async (d: any) => {
    if (!window.confirm(t("„{x}“ löschen?", { x: d.title }))) return;
    try { await api(`/api/documents/${d.doc_id}`, { method: "DELETE" }); setDoc(null); reload(); } catch (e: any) { window.alert(e.message); }
  };
  const search = async () => setHits(await api(`/api/projects/${pid}/knowledge/search?q=${encodeURIComponent(q)}`));
  return (
    <div className="mx-auto grid max-w-6xl gap-4 p-4 md:grid-cols-[280px_minmax(0,1fr)]">
      <div className="space-y-3">
        <h1 className="text-lg font-semibold">{t("Vertrag / LV")}</h1>
        {["legal", "project"].map((col) => (
          <div key={col}>
            <div className="mb-1 text-2xs uppercase tracking-wide text-slate-500">{t(col === "legal" ? "Rechtsgrundlagen (VOB/B aktuelle Fassung)" : "Projektunterlagen")}</div>
            <ul className="space-y-1">{(docs || []).filter((d) => d.collection === col).map((d) => (
              <li key={d.doc_id} className="group flex items-center"><button onClick={async () => { setHits(null); setDoc(await api(`/api/documents/${d.doc_id}`)); }} className="flex-1 rounded px-2 py-1 text-left text-sm hover:bg-white">{d.title} <span className="text-2xs text-slate-500">{t("{n} S.", { n: d.pages })}</span></button>
                {col === "project" && <button onClick={() => removeDoc(d)} className="rounded p-1 text-slate-400 opacity-60 hover:text-bad group-hover:opacity-100" aria-label={t("Löschen")}><Trash2 className="h-4 w-4" /></button>}</li>
            ))}</ul>
          </div>
        ))}
        <div className="card space-y-2 p-3">
          <div className="text-xs font-medium">{t("Dokument hochladen")}</div>
          <select className="w-full rounded border px-2 py-1 text-sm" value={docType} onChange={(e) => setDocType(e.target.value)}>
            {[["lv", "Leistungsverzeichnis (LV)"], ["vertrag", "Vertrag"], ["planlieferliste", "Planlieferliste"], ["protokoll", "Protokoll"], ["dokument", "Sonstiges"]].map(([v, l]) => <option key={v} value={v}>{t(l)}</option>)}
          </select>
          <label className="btn w-full cursor-pointer justify-center"><Upload className="h-4 w-4" /> {t("PDF / DOCX / Bild wählen")}
            <input type="file" className="hidden" accept=".pdf,.docx,.doc,.md,.txt,image/*" onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = ""; }} /></label>
          {upMsg && <p className="text-2xs text-slate-600">{upMsg}</p>}
        </div>
        <p className="text-2xs text-slate-600">{t("Normzitate in Schreiben stammen ausschließlich aus den Vorlagen. Die Wissensbasis dient dem Nachweis und der Suche (BM25 + BGE-M3, Rerank).")}</p>
      </div>
      <div className="space-y-3">
        <div className="flex gap-2">
          <input className="flex-1 rounded-md border px-3 py-1.5 text-sm" placeholder={t("z. B. Behinderung unverzüglich schriftlich")} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search()} />
          <button className="btn" onClick={search}>{t("Suchen")}</button>
        </div>
        {hits && <div className="space-y-2">{hits.map((h) => (
          <div key={h.chunk_id} className="card p-3 text-sm"><div className="mb-1 flex justify-between text-xs"><b>{h.title}</b><span className="text-slate-500">{h.doc_title} · {t("S. {n}", { n: h.page })} · {t("Relevanz")} {Number(h.relevance).toFixed(2)}</span></div><p className="whitespace-pre-wrap text-slate-700">{h.text.slice(0, 600)}</p></div>
        ))}</div>}
        {doc && !hits && (
          <div className="card space-y-3 p-4">
            <h2 className="font-semibold">{doc.title}</h2>
            {doc.pages.map((p: any) => <div key={p.page}><div className="text-2xs text-slate-500">{t("Seite {n}", { n: p.page })}</div><pre className="whitespace-pre-wrap font-sans text-sm">{p.text}</pre></div>)}
          </div>
        )}
      </div>
    </div>
  );
}
