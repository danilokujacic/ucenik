import { Badge } from "@/components/ui/badge";
import type { LectureStatus } from "@/lib/types/api";

const VARIANTS: Record<LectureStatus, "secondary" | "success" | "destructive"> = {
  pending: "secondary",
  generating: "secondary",
  ready: "success",
  failed: "destructive",
};

export function LectureStatusBadge({ status }: { status: LectureStatus }) {
  return (
    <Badge variant={VARIANTS[status]} className="capitalize">
      {status}
    </Badge>
  );
}
