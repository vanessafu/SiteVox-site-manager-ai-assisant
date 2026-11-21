"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { SOURCE_ICON } from "./EvidenceViewer";
import { useT } from "@/lib/i18n";

/** Bauhaus-Palette: Blau = Arbeit, Gelb = eingeschränkt, Rot = Stillstand, Schraffur = geplant, nicht begonnen. */
const HATCH = "repeating-linear-gradient(135deg, #161616 0 2px, transparent 2px 7px)";
const SEG: Record<string, { cls: string; style?: React.CSSProperties; label: string }> = {
  work: { cls: "bg-bh-blue", label: "Arbeit" },
  restricted: { cls: "bg-bh-yellow", label: "eingeschränkt" },
  idle: { cls: "bg-bh-red", label: "Stillstand" },
  planned_not_started: { cls: "bg-bh-paper border-2 border-bh-black", style: { backgroundImage: HATCH }, label: "geplant, nicht begonnen" },
};

const ICON_PX = 28; // Platzbedarf eines Symbols; engere Erfassungen weichen in die nächste Spur aus
const LANE_PX = 30;
const ROW_PX = 34;
const GRID = "grid grid-cols-[288px_minmax(0,1fr)_48px] gap-2 px-1.5"; // wie Bullet-Zeilen darüber

/** Tagesverlauf: Zeilen je Gerät/Kolonne, oben die Erfassungen (Ursache ↔ Wirkung auf einer Zeitachse). */
export default function DayTimeline({ tl, onMarker, onSegment }: { tl: any; onMarker: (m: any) => void; onSegment: (row: any, seg: any) => void }) {
  const { t } = useT();
  const h0 = parseInt(tl.start), h1 = parseInt(tl.end);
  const hours = Array.from({ length: h1 - h0 + 1 }, (_, i) => h0 + i);
  const axisRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [hover, setHover] = useState<string | null>(null);

  useEffect(() => {
    const el = axisRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Spuren zuweisen: jede Erfassung bleibt exakt an ihrer Uhrzeit, nur bei Überlappung eine Spur höher.
  const { markers, lanes } = useMemo(() => {
    const sorted = [...tl.markers].sort((a: any, b: any) => a.pos - b.pos);
    const lastX: number[] = [];
    const out = sorted.map((m: any) => {
      const x = m.pos * width;
      let lane = lastX.findIndex((lx) => x - lx >= ICON_PX);
      if (lane === -1) lane = lastX.length;
      lastX[lane] = x;
      return { ...m, lane };
    });
    return { markers: out, lanes: Math.max(1, lastX.length) };
  }, [tl.markers, width]);

  const markerH = lanes * LANE_PX;
  const rowsH = tl.rows.length * ROW_PX;
  const hovered = markers.find((m: any) => m.capture_id === hover);

  return (
    <div className="text-sm">
      <div className={GRID}>
        {/* Beschriftungen links */}
        <div>
          <div className="flex items-end pb-1.5 text-xs text-slate-500" style={{ height: markerH }}>{t("Erfassungen")}</div>
          {tl.rows.map((r: any) => (
            <div key={r.id} className="flex items-center truncate" style={{ height: ROW_PX }}>{t(r.name)}</div>
          ))}
        </div>

        {/* Zeitachse */}
        <div ref={axisRef} className="relative">
          {/* Stundenraster */}
          {hours.map((h) => (
            <span key={h} className={`pointer-events-none absolute w-px ${(h - h0) % 2 === 0 ? "bg-slate-200" : "bg-slate-100"}`}
              style={{ left: `${((h - h0) / (h1 - h0)) * 100}%`, top: markerH, height: rowsH }} />
          ))}

          {/* Erfassungen */}
          <div className="relative" style={{ height: markerH }}>
            {markers.map((m: any) => {
              const Icon = SOURCE_ICON[m.kind] || SOURCE_ICON.note;
              const bottom = m.lane * LANE_PX;
              return (
                <div key={m.capture_id} className="absolute -translate-x-1/2" style={{ left: `${m.pos * 100}%`, bottom }}>
                  {/* Stiel bis zur Achse, damit gestapelte Symbole ihre Uhrzeit zeigen */}
                  {m.lane > 0 && <span className="absolute left-1/2 top-full w-px -translate-x-1/2 bg-bh-black/40" style={{ height: bottom }} />}
                  <button onClick={() => onMarker(m)} title={`${m.time} ${m.title}`}
                    onMouseEnter={() => setHover(m.capture_id)} onMouseLeave={() => setHover(null)}
                    onFocus={() => setHover(m.capture_id)} onBlur={() => setHover(null)}
                    className={`relative mb-1 grid h-6 w-6 place-items-center rounded-full border-[1.5px] border-bh-black transition-colors ${
                      hover === m.capture_id ? "bg-bh-yellow" : "bg-white"} text-bh-black`}>
                    <Icon className="h-3.5 w-3.5" strokeWidth={2.25} />
                  </button>
                </div>
              );
            })}
          </div>

          {/* Geräte / Kolonnen */}
          {tl.rows.map((r: any) => (
            <div key={r.id} className="relative" style={{ height: ROW_PX }}>
              {r.segments.map((s: any, i: number) => {
                const st = SEG[s.status] || SEG.work;
                return (
                  <button key={i} onClick={() => onSegment(r, s)} title={`${t(st.label)} ${s.start}–${s.end}`}
                    className={`absolute top-1.5 h-5 hover:brightness-110 ${st.cls}`}
                    style={{ left: `${s.from_pct * 100}%`, width: `${(s.to_pct - s.from_pct) * 100}%`, ...st.style }} />
                );
              })}
            </div>
          ))}

          {/* Hilfslinie der markierten Erfassung */}
          {hovered && (
            <span className="pointer-events-none absolute w-0 border-l-[1.5px] border-dashed border-bh-black"
              style={{ left: `${hovered.pos * 100}%`, top: markerH - 4, height: rowsH + 4 }} />
          )}

          {/* Stundenachse */}
          <div className="relative h-6 border-t-[1.5px] border-bh-black text-xs text-slate-500">
            {hours.filter((h) => (h - h0) % 2 === 0).map((h) => (
              <span key={h} className="absolute top-0.5 -translate-x-1/2" style={{ left: `${((h - h0) / (h1 - h0)) * 100}%` }}>{String(h).padStart(2, "0")}</span>
            ))}
            {hovered && (
              <span className="absolute top-0.5 -translate-x-1/2 bg-bh-black px-1 font-medium text-white" style={{ left: `${hovered.pos * 100}%` }}>{hovered.time}</span>
            )}
          </div>
        </div>
        <span />
      </div>

      <div className="mt-2 flex flex-wrap gap-3 pl-[302px] text-xs text-slate-600">
        {Object.entries(SEG).map(([k, s]) => (
          <span key={k} className="inline-flex items-center gap-1.5">
            <span className={`inline-block h-3 w-4 ${s.cls}`} style={s.style} /> {t(s.label)}
          </span>
        ))}
      </div>
    </div>
  );
}
