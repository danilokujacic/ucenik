"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth/auth-context";
import type { UserRole } from "@/lib/types/api";
import { Spinner } from "@/components/ui/spinner";

/** Tokens live in localStorage (spec §1: "the frontend owns storage"), so
 * Next's proxy/middleware (edge, no localStorage access) can't gate routes.
 * This is a client-side UX guard only - the server's 401/403/404 responses
 * remain the real enforcement (spec §3.7). */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "unauthenticated") router.replace("/login");
  }, [status, router]);

  if (status !== "authenticated") {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner />
      </div>
    );
  }

  return <>{children}</>;
}

/** Role-gated UX only, same caveat as above - a mis-typed URL to a page the
 * role can't use bounces to /subjects rather than rendering a dead end. */
export function RequireRole({ roles, children }: { roles: UserRole[]; children: React.ReactNode }) {
  const { user, status } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "authenticated" && user && !roles.includes(user.role)) {
      router.replace("/subjects");
    }
  }, [status, user, roles, router]);

  if (status !== "authenticated" || !user || !roles.includes(user.role)) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <Spinner />
      </div>
    );
  }

  return <>{children}</>;
}
