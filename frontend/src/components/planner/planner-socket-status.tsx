import { Wifi, WifiOff, Loader2 } from "lucide-react";
import type { PlannerSocketStatus } from "@/lib/planner/use-planner-socket";
import { cn } from "@/lib/utils";

const CONFIG: Record<PlannerSocketStatus, { label: string; icon: typeof Wifi; className: string }> = {
  open: { label: "Live progress connected", icon: Wifi, className: "text-success" },
  connecting: { label: "Connecting…", icon: Loader2, className: "text-muted-foreground" },
  closed: { label: "Disconnected - reconnecting", icon: WifiOff, className: "text-warning" },
};

export function PlannerSocketStatusPill({ status }: { status: PlannerSocketStatus }) {
  const { label, icon: Icon, className } = CONFIG[status];
  return (
    <span className={cn("flex items-center gap-1.5 text-xs", className)}>
      <Icon className={cn("size-3.5", status === "connecting" && "animate-spin")} />
      {label}
    </span>
  );
}
