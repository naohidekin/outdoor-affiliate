import { BedDouble, Tent, Lamp, Snowflake, ArrowUpRight } from "lucide-react";
import type { getAvailableGearGuides, GearGuideId } from "@/lib/gearGuides";
import GuideLink from "./GuideLink";

const icons = { sleep: BedDouble, tent: Tent, light: Lamp, cooling: Snowflake };

export default function GearGuideTopics({ guides, placement = "home" }: {
  guides: ReturnType<typeof getAvailableGearGuides>;
  placement?: "home" | "guide";
}) {
  return <nav aria-label="目的からギアを選ぶ" className="grid grid-cols-2 gap-2 sm:gap-3">
    {guides.map((guide) => {
      const Icon = icons[guide.id as GearGuideId];
      return <GuideLink key={guide.id} guideId={guide.id} placement={placement}
        href={`${placement === "home" ? "/gear-guides" : ""}#${guide.id}`}
        className="group min-w-0 rounded-xl border border-line bg-white p-4 sm:p-5 hover:border-lake-600 hover:bg-lake-50/40 transition-colors">
        <div className="flex items-center justify-between gap-2 text-lake-600"><Icon size={22} aria-hidden="true" /><ArrowUpRight size={16} aria-hidden="true" /></div>
        <span className="block mt-3 text-base font-semibold leading-relaxed text-ink-strong">{guide.label}</span>
        <span className="block mt-1 text-sm text-slate-500 leading-relaxed">{guide.shortLabel}</span>
      </GuideLink>;
    })}
  </nav>;
}
