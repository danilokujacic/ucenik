import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("size-5 animate-spin text-muted-foreground", className)} />;
}

export { Spinner };
