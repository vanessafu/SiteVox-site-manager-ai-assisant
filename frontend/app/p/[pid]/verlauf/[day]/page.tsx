"use client";
import { useParams } from "next/navigation";
import DashboardView from "@/components/DashboardView";

/** Verlauf: das komplette Dashboard eines früheren Berichtstags. */
export default function HistoryDay() {
  const { day } = useParams<{ day: string }>();
  return <DashboardView day={day} />;
}
