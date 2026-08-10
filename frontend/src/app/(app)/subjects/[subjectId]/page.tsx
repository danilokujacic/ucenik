"use client";

import { use, useEffect } from "react";
import { useRouter } from "next/navigation";

/** No distinct "overview" beyond what the subject layout's header already
 * shows - land on Documents, the first tab, same as clicking it. */
export default function SubjectIndexPage({ params }: { params: Promise<{ subjectId: string }> }) {
  const { subjectId } = use(params);
  const router = useRouter();

  useEffect(() => {
    router.replace(`/subjects/${subjectId}/documents`);
  }, [subjectId, router]);

  return null;
}
