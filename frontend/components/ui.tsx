"use client";
import { useEffect, useState } from "react";
import { band, elapsed, pct, SPHERE_LABEL, DISCLAIMER } from "@/lib/api";
import { useT } from "@/lib/i18n";

const BAND_CLS: Record<string, string> = {
  green: "bg-ok-soft text-ok-text",
  yellow: "bg-warn-soft text-warn-text",
  red: "bg-bad-soft text-bad-text",
  none: "bg-slate-100 text-slate-600",
};

export function ConfidencePill({ value, title }: { value?: number | null; title?: string }) {
  const { t } = useT();
  const b = band(value);
  return (
    <span className={`pill ${BAND_CLS[b]}`} title={title || t("Konfidenz aus Belegen, ASR-Score, Sampling-Konsistenz, Retrieval und Regeln (keine LLM-Selbstauskunft)")}>
      {value === null || value === undefined ? "—" : value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
    </span>
  );
}

export function BandDot({ b }: { b: string }) {
  const c = b === "green" ? "bg-ok" : b === "yellow" ? "bg-warn" : b === "red" ? "bg-bad" : "bg-slate-300";
  return <span className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${c}`} />;
}

export function SphereChip({ sphere, confirmed }: { sphere: string; confirmed?: boolean }) {
  const { t } = useT();
  const cls = sphere === "AG" ? "bg-accent-soft text-accent-text" : sphere === "neutral" ? "bg-violet-100 text-violet-700" : "bg-slate-200 text-slate-700";
  return (
    <span className={`pill ${cls}`} title={confirmed ? t("von Bauleitung bestätigt") : t("Vorschlag – menschliche Bestätigung erforderlich")}>
      {t(SPHERE_LABEL[sphere] || sphere)}
      {!confirmed && <span className="font-normal opacity-70">· {t("Vorschlag")}</span>}
    </span>
  );
}

const LEVEL_CLS: Record<string, string> = {
  critical: "text-bad-text",
  warn: "text-warn-text",
  info: "text-accent-text",
  done: "text-ok-text",
  ok: "text-slate-600",
  none: "text-slate-500",
};

/** Zeit seit Feststellung – läuft live mit (Demo-Punkt: "unverzüglich" sichtbar machen). */
export function Elapsed({ from, level, label }: { from: string; level?: string; label?: string }) {
  const { t } = useT();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(t);
  }, []);
  return (
    <span className={`text-2xs ${LEVEL_CLS[level || "ok"]}`}>
      {label ? `${t(label)} · ` : ""}{t("seit {t}", { t: elapsed(from, now) })}
    </span>
  );
}

export function StatusChip({ status }: { status: string }) {
  const { t } = useT();
  const map: Record<string, string> = {
    Entwurf: "bg-warn-soft text-warn-text",
    Geprüft: "bg-accent-soft text-accent-text",
    Versendet: "bg-ok-soft text-ok-text",
    Verworfen: "bg-slate-200 text-slate-600 line-through",
  };
  return <span className={`pill ${map[status] || "bg-slate-100 text-slate-600"}`}>{t(status)}</span>;
}

export function Ratio({ r }: { r: number | null | undefined }) {
  const cls = r === null || r === undefined ? "text-slate-500" : r < 0.6 ? "text-bh-red" : r < 0.9 ? "text-warn-text" : "text-bh-blue"; // passend zu den Bauhaus-Balken
  return <span className={`font-medium tabular-nums ${cls}`}>{pct(r)}</span>;
}

export function Disclaimer({ className = "" }: { className?: string }) {
  const { t } = useT();
  return <div className={`text-center text-2xs text-slate-600 ${className}`}>„{t(DISCLAIMER)}“</div>;
}

export function Legend({ items }: { items: { cls: string; label: string }[] }) {
  const { t } = useT();
  return (
    <div className="mt-2 flex flex-wrap gap-3 text-xs text-slate-600">
      {items.map((i) => (
        <span key={i.label} className="inline-flex items-center gap-1">
          <span className={`inline-block h-3 w-4 rounded-sm ${i.cls}`} /> {t(i.label)}
        </span>
      ))}
    </div>
  );
}
