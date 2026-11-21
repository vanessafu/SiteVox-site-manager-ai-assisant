"use client";
import { ChevronRight } from "lucide-react";
import { dShort } from "@/lib/api";
import { useT } from "@/lib/i18n";

type Props = { overview: any; onSelect: (row: any) => void; dense?: boolean };

/** Gantt (Soll / Ist / Rückstand / Prognose / Vertragsfrist) mit Heute-Linie. */
export default function Gantt({ overview, onSelect, dense }: Props) {
  const { t } = useT();
  const { window: w, activities, today_idx } = overview;
  const n = w.end_idx - w.start_idx + 1;
  const x = (idx: number) => ((idx - w.start_idx) / n) * 100;
  const idxOf: Record<string, number> = Object.fromEntries(w.days.map((d: any) => [d.date, d.idx]));
  const todayX = x(today_idx + 1);
  return (
    <div className="text-sm">
      <div className="grid grid-cols-[288px_minmax(0,1fr)_20px] gap-2 px-1.5 text-xs text-slate-500">
        <span />
        <div className="relative h-4">
          {w.weeks.map((wk: any) => (
            <span key={wk.kw} className="absolute -translate-x-0 border-l border-slate-200 pl-1" style={{ left: `${x(wk.start_idx)}%` }}>KW{wk.kw}</span>
          ))}
        </div>
        <span />
      </div>
      <div className="relative">
        {activities.map((r: any) => {
          const dur = r.planned_finish_idx - r.planned_start_idx + 1;
          const istW = r.kind === "milestone" ? 0 : r.pct * dur;
          const sollW = r.kind === "milestone" ? 0 : r.planned_pct * dur;
          const istStart = r.actual_start ? idxOf[r.actual_start] ?? r.planned_start_idx : r.planned_start_idx;
          return (
            <div key={r.id} role="button" tabIndex={0} onClick={() => onSelect(r)} onKeyDown={(e) => e.key === "Enter" && onSelect(r)}
              className={`row-click grid grid-cols-[288px_minmax(0,1fr)_20px] items-center gap-2 px-1.5 ${dense ? "py-1" : "py-1.5"}`}>
              {/* kein Abschneiden: lange Namen (z. B. Vertragsfristen) brechen um */}
              <span className={`break-words leading-snug ${r.critical && r.kind !== "milestone" ? "font-medium" : ""}`} title={t(r.name)}>
                {t(r.name)}{r.critical && r.kind !== "milestone" && <span className="ml-1 text-2xs text-bh-red" title={t("kritischer Pfad")}>●</span>}
              </span>
              {/* Bauhaus: Soll = Papier mit Kontur, Ist = Blau, Rückstand = Rot, Prognose = schwarz gestrichelt */}
              <div className="relative h-4">
                {r.kind === "milestone" ? (
                  <>
                    <span className="absolute -top-1 -translate-x-1/2 text-base text-bh-black" style={{ left: `${x(r.planned_finish_idx + 1)}%` }} title={t("Vertragsfrist {d}", { d: dShort(r.planned_finish) })}>◆</span>
                    {r.delay_days > 0 && (
                      <span className="absolute -top-1 -translate-x-1/2 text-base text-bh-red" style={{ left: `${x(r.forecast_finish_idx + 1)}%` }} title={`${t("Prognose")} ${dShort(r.forecast_finish)}`}>◇</span>
                    )}
                  </>
                ) : (
                  <>
                    <div className="absolute top-0 h-4 border border-bh-black/25 bg-bh-paper" style={{ left: `${x(r.planned_start_idx)}%`, width: `${(dur / n) * 100}%` }} />
                    {istW > 0 && <div className="absolute top-0 h-4 bg-bh-blue" style={{ left: `${x(istStart)}%`, width: `${(istW / n) * 100}%` }} />}
                    {sollW > istW + 0.05 && (
                      <div className="absolute top-0 h-4 bg-bh-red" style={{ left: `${x(istStart) + (istW / n) * 100}%`, width: `${((sollW - istW) / n) * 100}%` }} title={t("Rückstand")} />
                    )}
                    {r.delay_days > 0 && (
                      <div className="absolute -top-0.5 h-5 border-2 border-dashed border-bh-black" style={{ left: `${x(r.forecast_start_idx)}%`, width: `${((r.forecast_finish_idx - r.forecast_start_idx + 1) / n) * 100}%` }} title={`${t("Prognose")} ${dShort(r.forecast_start)}–${dShort(r.forecast_finish)}`} />
                    )}
                  </>
                )}
              </div>
              <ChevronRight className="h-3.5 w-3.5 text-slate-500" />
            </div>
          );
        })}
        <div className="pointer-events-none absolute inset-y-0 grid w-full grid-cols-[288px_minmax(0,1fr)_20px] gap-2 px-1.5">
          <span />
          <div className="relative"><div className="absolute inset-y-0 border-l-2 border-bh-black" style={{ left: `${todayX}%` }} title={t("Heute")} /></div>
          <span />
        </div>
      </div>
    </div>
  );
}
