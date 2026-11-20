"use client";
import Sidebar from "@/components/Sidebar";
import { DrawerProvider } from "@/components/Drawer";
import { Disclaimer } from "@/components/ui";

/** Container-Büro: linke Spalte fest, rechts eigener vertikaler Scrollbereich. */
export default function OfficeLayout({ children }: { children: React.ReactNode }) {
  return (
    <DrawerProvider>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <main id="scroll-pane" className="min-h-0 flex-1 overflow-y-auto">{children}</main>
          <footer className="border-t border-slate-200 bg-white px-4 py-1.5"><Disclaimer /></footer>
        </div>
      </div>
    </DrawerProvider>
  );
}
