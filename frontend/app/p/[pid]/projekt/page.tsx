"use client";
/** Projekt bearbeiten: Stammdaten (Projekt, Vertrag, Auftraggeber, Standort) + Vorschläge aus dem Vertrag. */
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Pencil } from "lucide-react";
import { put, useApi } from "@/lib/api";
import { useT } from "@/lib/i18n";
import EditForm from "@/components/EditForm";
import ContractInfo from "@/components/ContractInfo";

const FIELDS = [
  { key: "name", label: "Kurzname", type: "text" as const, required: true },
  { key: "title", label: "Bauvorhaben", type: "text" as const },
  { key: "address", label: "Adresse Baustelle", type: "text" as const },
  { key: "coords", label: "Koordinaten Baustelle (Breite, Länge) – für das Wetter", type: "text" as const,
    help: "In Google Maps: Rechtsklick auf die Baustelle → erste Zeile (Koordinaten) anklicken = kopiert." },
  { key: "contract_no", label: "Vertragsnummer", type: "text" as const },
  { key: "contract_date", label: "Vertragsdatum", type: "date" as const },
  { key: "contract_basis", label: "Vertragsgrundlage", type: "text" as const },
  { key: "client.name", label: "Auftraggeber", type: "text" as const },
  { key: "client.address", label: "Adresse AG", type: "text" as const },
  { key: "client.representative", label: "Bevollmächtigter Vertreter", type: "text" as const },
  { key: "client.representative_role", label: "Funktion", type: "text" as const },
  { key: "client.email", label: "E-Mail AG (Empfänger der Anzeigen)", type: "text" as const },
  { key: "client.phone", label: "Telefon AG", type: "text" as const },
];

export default function ProjectEdit() {
  const { pid } = useParams<{ pid: string }>();
  const { t } = useT();
  const { data: master, reload } = useApi<any>(`/api/projects/${pid}/master`);
  if (!master) return <div className="p-6 text-sm text-slate-500">{t("lädt …")}</div>;
  const initial = {
    ...master, coords: master.lat != null ? `${master.lat}, ${master.lon}` : "",
    ...Object.fromEntries(Object.entries(master.client || {}).map(([k, v]) => [`client.${k}`, v])),
  };
  return (
    <div className="mx-auto max-w-3xl space-y-4 px-4 py-4 lg:px-6">
      <div className="flex items-center gap-2">
        <Link href={`/p/${pid}`} className="rounded p-1 hover:bg-slate-100" aria-label={t("Zurück")}><ArrowLeft className="h-5 w-5" /></Link>
        <h1 className="flex flex-1 items-center gap-2 text-xl font-semibold"><Pencil className="h-5 w-5" /> {t("Projekt bearbeiten")}</h1>
        <span className="text-xs text-slate-500">{pid}</span>
      </div>
      <ContractInfo pid={pid} onApplied={reload} />
      <div className="card p-4">
        {/* key: Formular nach „Übernehmen“ mit den neuen Stammdaten neu aufbauen */}
        <EditForm key={JSON.stringify(master)} fields={FIELDS} initial={initial}
          note="Empfänger und Vertragsnummer neuer Schreiben werden aus diesen Stammdaten übernommen."
          onSave={async (patch) => {
            const body: any = { client: {} };
            for (const [k, v] of Object.entries(patch)) k.startsWith("client.") ? (body.client[k.slice(7)] = v) : (body[k] = v);
            if (!Object.keys(body.client).length) delete body.client;
            await put(`/api/projects/${pid}/master`, body);
            reload();
          }} />
      </div>
    </div>
  );
}
