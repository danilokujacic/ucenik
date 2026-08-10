"use client";

import { useQuery } from "@tanstack/react-query";
import { getMyQuota } from "@/lib/api/users";
import { queryKeys } from "@/lib/query/keys";
import { Progress } from "@/components/ui/progress";

/** Live capability beyond the spec doc - see the frontend build plan's
 * Context section. Small, quiet indicator only; quota exhaustion still
 * surfaces primarily as a 429 at the point of use (chat/planner). */
export function QuotaIndicator() {
  const { data } = useQuery({
    queryKey: queryKeys.quota(),
    queryFn: getMyQuota,
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  if (!data) return null;

  const pct = data.limit > 0 ? Math.min(100, Math.round((data.used_tokens / data.limit) * 100)) : 0;

  return (
    <div className="hidden w-36 flex-col gap-1 sm:flex" title={`${data.used_tokens.toLocaleString()} / ${data.limit.toLocaleString()} tokens today`}>
      <div className="flex justify-between text-[11px] text-muted-foreground">
        <span>Daily usage</span>
        <span>{pct}%</span>
      </div>
      <Progress value={pct} className="h-1.5" />
    </div>
  );
}
