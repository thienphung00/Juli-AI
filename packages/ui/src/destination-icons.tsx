import { BarChart3, ClipboardCheck } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export type DestinationIconName = "decisions" | "analytics";

const DESTINATION_ICON_MAP: Record<DestinationIconName, LucideIcon> = {
  decisions: ClipboardCheck,
  analytics: BarChart3,
};

export interface DestinationIconProps {
  name: DestinationIconName;
}

export function DestinationIcon({ name }: DestinationIconProps) {
  const Icon = DESTINATION_ICON_MAP[name];

  return (
    <Icon
      aria-hidden="true"
      className="juli-destination-icon"
      strokeWidth={2}
    />
  );
}
