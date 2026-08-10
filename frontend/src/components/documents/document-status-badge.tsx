import { Badge } from "@/components/ui/badge";
import type { DocumentStatus } from "@/lib/types/api";

const VARIANTS: Record<DocumentStatus, "secondary" | "success" | "destructive"> = {
  pending: "secondary",
  processing: "secondary",
  ready: "success",
  failed: "destructive",
};

export function DocumentStatusBadge({ status }: { status: DocumentStatus }) {
  return (
    <Badge variant={VARIANTS[status]} className="capitalize">
      {status}
    </Badge>
  );
}
