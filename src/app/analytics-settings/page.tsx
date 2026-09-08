import type { Metadata } from "next";
import AnalyticsPreference from "@/components/AnalyticsPreference";
export const metadata: Metadata = { title: "アクセス計測の設定", robots: { index: false, follow: false } };
export default function Page() { return <AnalyticsPreference />; }
