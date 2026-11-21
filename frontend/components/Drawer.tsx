"use client";
import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { FolderOpen, Pencil, X } from "lucide-react";
import { EvidenceCard } from "./EvidenceViewer";
import { useT } from "@/lib/i18n";

export type DrawerItem = {
  title: string;
  subtitle?: string;
  body?: ReactNode;
  evidence?: string[];
  edit?: { label?: string; href?: string; onClick?: () => void };
};

const Ctx = createContext<{ open: (i: DrawerItem) => void; close: () => void }>({ open: () => {}, close: () => {} });
export const useDrawer = () => useContext(Ctx);

/** Detail-Schublade von rechts – unterbricht die Scrollposition nicht. Jedes klickbare Element öffnet sie. */
export function DrawerProvider({ children }: { children: ReactNode }) {
  const [item, setItem] = useState<DrawerItem | null>(null);
  const [showEv, setShowEv] = useState(false);
  const router = useRouter();
  const { t } = useT();
  const open = useCallback((i: DrawerItem) => {
    setItem(i);
    setShowEv(false);
  }, []);
  const close = useCallback(() => setItem(null), []);
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && setItem(null);
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, []);
  return (
    <Ctx.Provider value={{ open, close }}>
      {children}
      <div className={`fixed inset-0 z-40 bg-slate-900/20 transition-opacity ${item ? "opacity-100" : "pointer-events-none opacity-0"}`} onClick={close} />
      <aside
        className={`fixed right-0 top-0 z-50 flex h-full w-full max-w-[720px] flex-col border-l border-slate-200 bg-white shadow-xl transition-transform duration-200 ${item ? "translate-x-0" : "translate-x-full"}`}
        aria-hidden={!item}
      >
        {item && (
          <>
            <header className="flex items-start gap-2 border-b p-4">
              <div className="min-w-0 flex-1">
                <h3 className="font-semibold">{item.title}</h3>
                {item.subtitle && <p className="text-xs text-slate-600">{item.subtitle}</p>}
              </div>
              <button onClick={close} className="rounded p-1 hover:bg-slate-100" aria-label={t("Schließen")}><X className="h-[18px] w-[18px]" /></button>
            </header>
            <div className="flex-1 space-y-3 overflow-y-auto p-4 text-sm">
              {item.body}
              <div className="flex gap-2 pt-1">
                <button className="btn" disabled={!item.evidence?.length} onClick={() => setShowEv((s) => !s)}>
                  <FolderOpen className="h-[18px] w-[18px]" /> {t("Belege öffnen")}{item.evidence?.length ? ` (${item.evidence.length})` : ""}
                </button>
                <button className="btn" disabled={!item.edit}
                  onClick={() => { if (item.edit?.onClick) item.edit.onClick(); else if (item.edit?.href) { router.push(item.edit.href); close(); } }}>
                  <Pencil className="h-[18px] w-[18px]" /> {t(item.edit?.label || "Bearbeiten")}
                </button>
              </div>
              {showEv && <div className="space-y-2">{item.evidence!.map((id) => <EvidenceCard key={id} id={id} />)}</div>}
            </div>
          </>
        )}
      </aside>
    </Ctx.Provider>
  );
}
