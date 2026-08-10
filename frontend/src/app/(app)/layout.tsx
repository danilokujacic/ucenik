import { RequireAuth } from "@/components/auth/guards";
import { NavShell } from "@/components/layout/nav-shell";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <RequireAuth>
      <NavShell>{children}</NavShell>
    </RequireAuth>
  );
}
