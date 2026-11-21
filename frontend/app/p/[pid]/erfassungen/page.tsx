"use client";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Pencil, Trash2 } from "lucide-react";
import { api, dLong, time, useApi } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { EvidenceCard, SOURCE_ICON } from "@/components/EvidenceViewer";
import { useDrawer } from "@/components/Drawer";
import EditForm from "@/components/EditForm";

/** Tages-Timeline aller Erfassungen mit Zusammenfassung, Belegen, Bearbeiten und Löschen. */
export default function Captures() {
  const { pid } = useParams<{ pid: string }>();
  const { data: caps, reload } = useApi<any[]>(`/api/projects/${pid}/captures`, 5_000);
  const [open, setOpen] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const drawer = useDrawer();
  const { t } = useT();
  const days = Array.from(new Set((caps || []).map((c) => c.date))).sort().reverse();

  // Deep-Link /erfassungen#CAP-…: Die Liste lädt asynchron, daher greift der Browser-Anker nicht –
  // nach dem Laden selbst hinscrollen, Belege aufklappen und den Eintrag kurz hervorheben.
  const [focus, setFocus] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const handled = useRef<string | null>(null);
  useEffect(() => {
    const read = () => {
      const id = decodeURIComponent(window.location.hash.slice(1));
      if (id) { setFocus(id); handled.current = null; }
    };
    read();
    window.addEventListener("hashchange", read);
    return () => window.removeEventListener("hashchange", read);
  }, []);
  useEffect(() => {
    if (!focus || !caps || handled.current === focus || !caps.some((c) => c.capture_id === focus)) return;
    handled.current = focus;
    setOpen(focus);
    setFlash(focus);
    requestAnimationFrame(() => document.getElementById(focus)?.scrollIntoView({ behavior: "smooth", block: "center" }));
  }, [focus, caps]);
  useEffect(() => {
    if (!flash) return;
    const timer = setTimeout(() => setFlash(null), 2500);
    return () => clearTimeout(timer);
  }, [flash]);

  const remove = async (c: any) => {
    if (!window.confirm(t("„{x}“ löschen? Abgeleitete Mengen, Belege und Ereignisse werden mit entfernt (Audit-Log).", { x: t(c.title) }))) return;
    setErr(null);
    try {
      await api(`/api/captures/${c.capture_id}`, { method: "DELETE" });
      reload();
    } catch (e: any) {
      setErr(e.message);
    }
  };
  const edit = async (c: any) => {
    const full = await api(`/api/captures/${c.capture_id}`);
    drawer.open({
      title: `${t("Erfassung bearbeiten")}: ${t(c.title)}`, subtitle: c.capture_id,
      body: <EditForm
        note="Text korrigieren (z. B. Erkennungsfehler im Transkript) und optional neu auswerten lassen. Die Originaldatei bleibt erhalten."
        fields={[
          { key: "title", label: "Titel", type: "text" },
          { key: "summary", label: "Zusammenfassung", type: "textarea" },
          ...(c.kind !== "document" ? [{ key: "text", label: c.kind === "audio" ? "Transkript" : "Text", type: "textarea" as const }] : []),
          { key: "reanalyze", label: "Nach dem Speichern neu auswerten (Ereignisse/Mengen neu ableiten)", type: "checkbox" as const },
        ]}
        initial={{ title: full.title, summary: full.summary, text: full.text, reanalyze: false }}
        onSave={async (patch) => { await api(`/api/captures/${c.capture_id}`, { method: "PATCH", body: JSON.stringify(patch) }); reload(); }}
        onDelete={async () => { await api(`/api/captures/${c.capture_id}`, { method: "DELETE" }); reload(); drawer.close(); }}
        deleteConfirm="Erfassung inkl. Datei löschen? Abgeleitete Mengen, Belege und Ereignisse werden mit entfernt (Audit-Log)." />,
    });
  };

  return (
    <div className="mx-auto max-w-3xl p-4">
      <h1 className="mb-4 text-lg font-semibold">{t("Erfassungen")}</h1>
      {err && <p className="mb-3 rounded-md bg-bad-soft p-2 text-sm text-bad-text">{err}</p>}
      {days.map((d) => (
        <section key={d} className="mb-6">
          <h2 className="mb-2 text-sm font-medium text-slate-600">{dLong(d)}</h2>
          <ol className="relative space-y-2 border-l border-slate-200 pl-4">
            {(caps || []).filter((c) => c.date === d).map((c) => {
              const Icon = SOURCE_ICON[c.kind] || SOURCE_ICON.note;
              return (
                <li key={c.capture_id} id={c.capture_id}
                  className={`card scroll-mt-20 p-3 transition-shadow duration-700 ${flash === c.capture_id ? "ring-[3px] ring-bh-yellow" : ""}`}>
                  <span className="absolute -left-[9px] mt-1 h-4 w-4 rounded-full border-2 border-white bg-slate-400" />
                  <div className="flex items-start gap-2">
                    <button className="flex min-w-0 flex-1 items-start gap-2 text-left" onClick={() => setOpen(open === c.capture_id ? null : c.capture_id)}>
                      <Icon className="mt-0.5 h-[18px] w-[18px] shrink-0 text-slate-600" />
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2 text-sm font-medium"><span className="font-mono text-xs text-slate-500">{time(c.captured_at)}</span>{t(c.title)}
                          {c.status !== "done" && <span className="pill bg-warn-soft text-warn-text">{c.status}</span>}
                          {c.text_edited && <span className="pill bg-accent-soft text-accent-text">{t("korrigiert")}</span>}
                          {c.asr_score != null && <span className="pill bg-slate-100 text-slate-600">ASR {c.asr_score.toFixed(2)}</span>}</div>
                        <div className="text-xs text-slate-600">{c.summary}</div>
                        {c.event_ids?.length > 0 && <div className="mt-1 text-2xs text-accent-text">→ {c.event_ids.join(", ")}</div>}
                      </div>
                    </button>
                    <button className="btn-xs" onClick={() => edit(c)} title={t("Bearbeiten")}><Pencil className="h-3.5 w-3.5" /></button>
                    <button className="btn-xs text-bad-text" onClick={() => remove(c)} title={t("Löschen")}><Trash2 className="h-3.5 w-3.5" /></button>
                  </div>
                  {c.minutes && (
                    <div className="mt-2 rounded bg-slate-50 p-2 text-xs">
                      <ul className="list-disc pl-4">{c.minutes.summary.map((s: string) => <li key={s}>{s}</li>)}</ul>
                      <div className="mt-2 font-medium">{t("Offene Punkte & Termine")}</div>
                      <ul className="space-y-0.5">{c.minutes.open_items.map((o: any) => <li key={o.topic}>• {o.topic} – {o.responsible} – <b>{o.due ? dLong(o.due) : t("ohne Termin")}</b></li>)}</ul>
                    </div>
                  )}
                  {open === c.capture_id && <div className="mt-2 space-y-2">{c.evidence_ids.map((id: string) => <EvidenceCard key={id} id={id} />)}</div>}
                </li>
              );
            })}
          </ol>
        </section>
      ))}
    </div>
  );
}
