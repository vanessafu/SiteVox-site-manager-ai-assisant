"use client";
import { useParams } from "next/navigation";
import { Pencil, Plus } from "lucide-react";
import { api, dShort, num, pct, post, put, useApi } from "@/lib/api";
import { useT } from "@/lib/i18n";
import Gantt from "@/components/Gantt";
import { useDrawer } from "@/components/Drawer";
import EditForm, { ACTIVITY_FIELDS, predsToString } from "@/components/EditForm";
import { Legend } from "@/components/ui";

export default function Schedule() {
  const { pid } = useParams<{ pid: string }>();
  const { data, reload } = useApi<any>(`/api/projects/${pid}/schedule`);
  const { data: raw, reload: reloadRaw } = useApi<any[]>(`/api/projects/${pid}/activities`);
  const drawer = useDrawer();
  const { t } = useT();
  const refresh = () => { reload(); reloadRaw(); };
  if (!data) return <div className="p-6 text-slate-500">{t("lädt …")}</div>;

  const edit = (id: string) => {
    const a = raw?.find((x) => x.id === id);
    if (!a) return;
    drawer.open({
      title: `${t("Vorgang bearbeiten")}: ${a.name}`, subtitle: a.id,
      body: <EditForm fields={ACTIVITY_FIELDS} initial={{ ...a, preds: predsToString(a.preds), aliases: (a.aliases || []).join("; ") }}
        note="Gantt, Soll-Ist, kritischer Pfad und Prognose werden aus dem geänderten Bauzeitenplan neu berechnet."
        onSave={async (patch) => { await put(`/api/projects/${pid}/activities/${id}`, patch); refresh(); }}
        onDelete={async () => { await api(`/api/projects/${pid}/activities/${id}`, { method: "DELETE" }); refresh(); drawer.close(); }} />,
    });
  };
  const create = () =>
    drawer.open({
      title: t("Neuer Vorgang"),
      body: <EditForm fields={[{ key: "id", label: "ID", type: "text", help: "leer = automatisch" }, ...ACTIVITY_FIELDS]}
        initial={{ kind: "task", start: data.date, finish: data.date }}
        onSave={async (patch) => { await post(`/api/projects/${pid}/activities`, { kind: "task", ...patch }); refresh(); }} />,
    });

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-4">
      <div className="flex items-center gap-2">
        <h1 className="text-lg font-semibold">{t("Bauzeitenplan · Stand {d}", { d: dShort(data.date) })}</h1>
        <button className="btn ml-auto" onClick={create}><Plus className="h-4 w-4" /> {t("Neuer Vorgang")}</button>
      </div>
      <div className="card p-3">
        <Gantt overview={data} onSelect={(r) => edit(r.id)} />
        <div className="pl-[144px]"><Legend items={[{ cls: "bg-ok", label: "Ist" }, { cls: "border border-slate-300 bg-slate-100", label: "Soll" }, { cls: "bg-bad", label: "Rückstand" }, { cls: "border border-dashed border-bad", label: "Prognose" }]} /></div>
      </div>
      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-slate-600"><tr>{["ID", "Vorgang", "LV", "Soll", "Prognose", "Verzug", "Puffer", "Ist", "Menge", ""].map((h, i) => <th key={i} className="px-2 py-2 font-medium">{h && t(h)}</th>)}</tr></thead>
          <tbody>
            {data.activities.map((r: any) => (
              <tr key={r.id} onClick={() => edit(r.id)} className={`cursor-pointer border-t hover:bg-slate-50 ${r.critical ? "font-medium" : ""}`}>
                <td className="px-2 py-1.5">{r.id}</td><td className="px-2 py-1.5">{r.name}{r.critical && " ●"}</td><td className="px-2 py-1.5">{r.lv_pos}</td>
                <td className="px-2 py-1.5">{dShort(r.planned_start)}–{dShort(r.planned_finish)}</td><td className="px-2 py-1.5">{dShort(r.forecast_start)}–{dShort(r.forecast_finish)}</td>
                <td className={`px-2 py-1.5 ${r.delay_days > 0 ? "text-bad-text" : ""}`}>{t("{n} AT", { n: r.delay_days > 0 ? `+${r.delay_days}` : r.delay_days })}</td>
                <td className="px-2 py-1.5">{r.total_float}</td><td className="px-2 py-1.5">{pct(r.pct)}</td><td className="px-2 py-1.5">{num(r.cum)} / {num(r.qty)} {r.unit}</td>
                <td className="px-2 py-1.5"><Pencil className="h-3.5 w-3.5 text-slate-500" /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.impact.map((c: any) => <p key={c.root} className={`text-sm ${c.critical ? "text-bad-text" : "text-slate-600"}`}>{t(c.text)}</p>)}
      <p className="text-2xs text-slate-600">{t("Berechnung deterministisch (CPM auf Arbeitstagen, Prognose = Restmenge / Ø-Leistung der letzten 3 AT, Blockaden aus Ereignissen). Import: Excel-Bauzeitenplan.")}</p>
    </div>
  );
}
