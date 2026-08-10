import type { LucideIcon } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/** Shared empty/error/not-found presentation - spec §3.7 wants 404 and 403
 * copy to read distinctly, so callers pass their own message rather than
 * this component guessing from a status code. */
export function StateCard({
  icon: Icon,
  title,
  description,
  className,
}: {
  icon?: LucideIcon;
  title: string;
  description?: string;
  className?: string;
}) {
  return (
    <Card className={className}>
      <CardContent className={cn("flex flex-col items-center gap-2 py-12 text-center")}>
        {Icon && <Icon className="size-8 text-muted-foreground" />}
        <p className="font-medium">{title}</p>
        {description && <p className="max-w-md text-sm text-muted-foreground">{description}</p>}
      </CardContent>
    </Card>
  );
}
