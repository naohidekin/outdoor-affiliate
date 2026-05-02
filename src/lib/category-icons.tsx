import {
  Tent,
  Lamp,
  Flame,
  Backpack,
  Snowflake,
  Mountain,
  Armchair,
  Table,
  ThermometerSnowflake,
  Shirt,
  Footprints,
  Cloudy,
  Thermometer,
  Wind,
  Users,
  CloudRain,
} from "lucide-react";

type IconSize = "sm" | "md" | "lg" | "xl";

const SIZE_MAP: Record<IconSize, string> = {
  sm: "w-3.5 h-3.5",
  md: "w-6 h-6",
  lg: "w-8 h-8",
  xl: "w-10 h-10",
};

const ICON_COMPONENTS: Record<
  string,
  React.ComponentType<{ className?: string; strokeWidth?: number }>
> = {
  tent: Tent,
  light: Lamp,
  burner: Flame,
  backpack: Backpack,
  "sleeping-bag": Snowflake,
  shoes: Footprints,
  chair: Armchair,
  table: Table,
  cooler: ThermometerSnowflake,
  wear: Shirt,
  firepit: Flame,
  tarp: Cloudy,
  // シーン別カテゴリ
  "heat-safety": Thermometer,
  "cold-safety": Wind,
  "family-first": Users,
  "rain-safety": CloudRain,
  // タンブラー（既存カテゴリ補完）
  tumbler: ThermometerSnowflake,
  "insect-repellent": Mountain,
};

export function getCategoryIcon(
  slug: string,
  size: IconSize = "md",
  strokeWidth?: number
): React.ReactNode {
  const Icon = ICON_COMPONENTS[slug];
  if (!Icon) return <Mountain className={SIZE_MAP[size]} />;
  return <Icon className={SIZE_MAP[size]} strokeWidth={strokeWidth} />;
}
