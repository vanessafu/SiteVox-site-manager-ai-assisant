"use client";
import { SOURCE_ICON } from "./EvidenceViewer";
import { Legend } from "./ui";
import { useT } from "@/lib/i18n";

const SEG: Record<string, string> = {
  work: "bg-ok",
  restricted: "bg-warn",
  idle: "bg-bad",
  planned_not_started: "bg-slate-100 border-2 border-dashed border-bad",
};

/** Tagesverlauf 07–17 Uhr: Zeilen je Gerät/Kolonne, oben die Erfassungen (Ursache ↔ Wirkung auf einer Achse). */
export default function DayTimeline({ tl, onMarker, onSegment }: { tl: any; onMarker: (m: any) => void; onSegment: (row: any, seg: any) => void }) {
  const { t } = useT();
  const h0 = parseInt(tl.start), h1 = parseInt(tl.end);
  const hours = Array.from({ length: h1 - h0 + 1 }, (_, i) => h0 + i).filter((h) => (h - h0) % 2 === 0);
  return (
    <div className="text-xs">
      <div className="grid grid-cols-[136px_minmax(0,1fr)_48px] gap-2 px-1.5">
        <span className="text-2xs text-slate-500">{t("Erfassungen")}</span>
        <div className="relative h-7">
          {tl.markers.map((m: any, i: number) => {
            const Icon = SOURCE_ICON[m.kind] || SOURCE_ICON.note;
            const prev = tl.markers[i - 1];
            const nudge = prev && Math.abs(prev.pos - m.pos) < 0.02 ? 10 : 0;
            return (
              <button key={m.capture_id} onClick={() => onMarker(m)} title={`${m.time} ${m.title}`}
                className="absolute top-0 -translate-x-1/2 rounded p-0.5 text-slate-600 hover:bg-accent-soft hover:text-accent-text"
                style={{ left: `calc(${m.pos * 100}% + ${nudge}px)` }}>
                <Icon className="h-5 w-5" />
              </button>
            );
          })}
        </div>
        <span />
      </div>
      {tl.rows.map((r: any) => (
        <div key={r.id} className="grid grid-cols-[136px_minmax(0,1fr)_48px] items-center gap-2 px-1.5 py-1.5">
          <span className="truncate">{r.name}</span>
          <div className="relative h-5">
            {r.segments.map((s: any, i: number) => (
              <button key={i} onClick={() => onSegment(r, s)} title={`${s.start}–${s.end}`}
                className={`absolute top-0 h-5 rounded hover:brightness-95 ${SEG[s.status]}`}
                style={{ left: `${s.from_pct * 100}%`, width: `${(s.to_pct - s.from_pct) * 100}%` }} />
            ))}
          </div>
          <span />
        </div>
      ))}
      <div className="grid grid-cols-[136px_minmax(0,1fr)_48px] gap-2 px-1.5 text-2xs text-slate-500">
        <span />
        <div className="relative h-4">
          {hours.map((h) => (
            <span key={h} className="absolute -translate-x-1/2" style={{ left: `${((h - h0) / (h1 - h0)) * 100}%` }}>{String(h).padStart(2, "0")}</span>
          ))}
        </div>
        <span />
      </div>
      <div className="pl-[144px]">
        <Legend items={[{ cls: "bg-ok", label: "Arbeit" }, { cls: "bg-warn", label: "eingeschränkt" }, { cls: "bg-bad", label: "Stillstand" },
          { cls: "border border-dashed border-bad", label: "geplant, nicht begonnen" }]} />
      </div>
    </div>
  );
}
