"use client";
import { useCallback, useEffect, useState } from "react";
import { locale } from "./i18n";

// Alle Aufrufe laufen über die Next-Rewrites (/api → FastAPI), damit Handy und Tablet dieselbe Origin nutzen.
export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: init?.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json", ...init?.headers } : init?.headers,
  });
  if (!res.ok) {
    let detail: any = res.statusText;
    try {
      detail = (await res.json()).detail;
    } catch {}
    throw Object.assign(new Error(typeof detail === "string" ? detail : JSON.stringify(detail)), { status: res.status, detail });
  }
  return res.json();
}

export const post = <T = any>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
export const put = <T = any>(path: string, body?: unknown) => api<T>(path, { method: "PUT", body: JSON.stringify(body) });

export function useApi<T = any>(path: string | null, pollMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    if (!path) return;
    try {
      setData(await api<T>(path));
      setError(null);
    } catch (e: any) {
      setError(e.message);
    }
  }, [path]);
  useEffect(() => {
    load();
    if (!pollMs) return;
    const t = setInterval(load, pollMs);
    return () => clearInterval(t);
  }, [load, pollMs]);
  return { data, error, reload: load, setData };
}

// ------------------------------------------------------------------ Formatierung (de-DE)
export const pct = (x: number | null | undefined, digits = 0) =>
  x === null || x === undefined ? "—" : `${(x * 100).toLocaleString(locale(), { minimumFractionDigits: digits, maximumFractionDigits: digits })} %`;
export const num = (x: number | null | undefined) =>
  x === null || x === undefined ? "—" : x.toLocaleString(locale(), { maximumFractionDigits: 2 });
export const dShort = (iso?: string | null) => {
  if (!iso) return "—";
  const d = new Date(iso.length === 10 ? iso + "T12:00:00" : iso);
  return locale() === "de-DE" ? d.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" }) + "." : d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
};
export const dLong = (iso?: string | null) =>
  iso ? new Date(iso.length === 10 ? iso + "T12:00:00" : iso).toLocaleDateString(locale(), { weekday: "short", day: "2-digit", month: "2-digit", year: "numeric" }) : "—";
export const time = (iso?: string | null) => (iso ? iso.slice(11, 16) : "—");
export const band = (c: number | null | undefined) => (c === null || c === undefined ? "none" : c >= 0.8 ? "green" : c >= 0.5 ? "yellow" : "red");

export function elapsed(fromIso: string, now = Date.now()) {
  const ms = Math.max(0, now - new Date(fromIso).getTime());
  const h = Math.floor(ms / 3.6e6);
  const m = Math.floor((ms % 3.6e6) / 6e4);
  if (h >= 48) return `${Math.floor(h / 24)} ${locale() === "de-DE" ? "T" : "d"} ${h % 24} h`;
  return h ? `${h} h ${m.toString().padStart(2, "0")} min` : `${m} min`;
}

export const SPHERE_LABEL: Record<string, string> = { AG: "AG-Sphäre", AN: "AN-Sphäre", neutral: "neutral" }; // via t() übersetzen
export const STATUS_LABEL: Record<string, string> = {
  open: "offen", draft: "Entwurf", released: "Geprüft", sent: "Versendet", logged: "Bautagebuch", dismissed: "verworfen",
};
export const RES_STATUS: Record<string, string> = {
  work: "Arbeit", restricted: "eingeschränkt", idle: "Stillstand", planned_not_started: "geplant, nicht begonnen",
};
export const DISCLAIMER = "Entwurf – keine Rechtsberatung, Prüfung durch Bauleitung/Unternehmen erforderlich";
