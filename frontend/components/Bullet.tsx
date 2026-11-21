"use client";
import { AlertTriangle } from "lucide-react";
import { Ratio } from "./ui";
import { useT } from "@/lib/i18n";

const SOLL_POS = 0.8; // Position der Tagessoll-Linie im Balken
// Bauhaus: Blau = Soll erreicht, Gelb = knapp darunter, Rot = deutlich darunter
const FILL: Record<string, string> = { red: "bg-bh-red", yellow: "bg-bh-yellow", green: "bg-bh-blue", none: "bg-slate-300" };

/** Bullet-Chart: Strich = Tagessoll, Füllung = Ist. Über dem Strich = übererfüllt. Nur eine Prozentzahl je Zeile. */
export function BulletRow({ b, onClick }: { b: any; onClick: () => void }) {
  const { t } = useT();
  const w = Math.min(1, (b.ratio ?? 0) * SOLL_POS) * 100;
  return (
    <div role="button" tabIndex={0} onClick={onClick} onKeyDown={(e) => e.key === "Enter" && onClick()}
      className="row-click grid grid-cols-[288px_minmax(0,1fr)_48px] items-center gap-2 px-1.5 py-1.5 text-sm">
      <span className="truncate" title={t(b.name)}>{t(b.name)}</span>
      <div className="relative h-5 bg-bh-paper">
        <div className={`absolute left-0 top-0 h-5 ${FILL[b.color]}`} style={{ width: `${w}%` }} />
        <div className="absolute -top-1.5 h-8 border-l-[3px] border-bh-black" style={{ left: `${SOLL_POS * 100}%` }} title={t("Tagessoll")} />
      </div>
      <span className="text-right"><Ratio r={b.ratio} /></span>
    </div>
  );
}

export function ExtraWorkRow({ e, onClick }: { e: any; onClick: () => void }) {
  const { t } = useT();
  return (
    <div role="button" tabIndex={0} onClick={onClick} onKeyDown={(k) => k.key === "Enter" && onClick()}
      className="row-click grid grid-cols-[288px_minmax(0,1fr)_48px] items-center gap-2 px-1.5 py-1.5 text-sm">
      <span className="truncate text-warn-text">+ {e.attrs?.ordered_by ? t("Zusatzleistung") : t(e.label)}</span>
      <div className="relative flex h-7 items-center border-2 border-dashed border-bh-yellow px-1.5 text-xs text-warn-text">
        <span className="truncate">{e.cause} · {t(e.attrs?.not_in_lv ? "nicht im LV" : "LV prüfen")} · {t("potenzieller Nachtrag")}</span>
      </div>
      <span className="text-right"><AlertTriangle className="ml-auto h-4 w-4 text-warn" /></span>
    </div>
  );
}
