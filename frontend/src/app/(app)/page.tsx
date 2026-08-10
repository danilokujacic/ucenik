"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth/auth-context";
import { Spinner } from "@/components/ui/spinner";

/** "/" itself just routes to the role-appropriate home (spec §3.1 point 1):
 * admin -> user management, teacher/student -> subject list. */
export default function HomePage() {
  const { user } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!user) return;
    router.replace(user.role === "admin" ? "/admin/users" : "/subjects");
  }, [user, router]);

  return (
    <div className="flex min-h-[50vh] items-center justify-center">
      <Spinner />
    </div>
  );
}
