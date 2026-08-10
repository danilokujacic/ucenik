"use client";

import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Upload } from "lucide-react";
import { uploadDocument } from "@/lib/api/documents";
import { queryKeys } from "@/lib/query/keys";
import { describeError } from "@/lib/errors";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";

const ALLOWED_TYPES = [
  "text/plain",
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
];

export function UploadDocumentButton({ subjectId }: { subjectId: string }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: (file: File) => uploadDocument(subjectId, file),
    onSuccess: (doc) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.documents(subjectId) });
      toast.success(`${doc.filename} uploaded - processing.`);
    },
    onError: (err) => toast.error(describeError(err)),
  });

  function handleFile(file: File | undefined) {
    if (!file) return;
    // Client-side pre-check mirrors the server's real rules (415/413) so a
    // bad pick fails fast instead of round-tripping first.
    if (!ALLOWED_TYPES.includes(file.type)) {
      toast.error("Unsupported file type. Allowed: .txt, .pdf, .docx, .pptx, .xlsx.");
      return;
    }
    if (file.size > 50 * 1024 * 1024) {
      toast.error("File is too large (max 50MB).");
      return;
    }
    mutation.mutate(file);
  }

  return (
    <div
      className="flex flex-col gap-2"
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        handleFile(e.dataTransfer.files?.[0]);
      }}
    >
      <input
        ref={inputRef}
        type="file"
        className="hidden"
        accept=".txt,.pdf,.docx,.pptx,.xlsx"
        onChange={(e) => {
          handleFile(e.target.files?.[0]);
          e.target.value = "";
        }}
      />
      <Button
        onClick={() => inputRef.current?.click()}
        disabled={mutation.isPending}
        variant={dragOver ? "secondary" : "default"}
      >
        {mutation.isPending ? <Spinner className="size-4 text-current" /> : <Upload />}
        Upload document
      </Button>
    </div>
  );
}
