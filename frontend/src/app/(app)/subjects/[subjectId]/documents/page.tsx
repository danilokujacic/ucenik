"use client";

import { use, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Download, FileText, Trash2 } from "lucide-react";
import { listDocuments, deleteDocument, downloadDocument } from "@/lib/api/documents";
import { queryKeys } from "@/lib/query/keys";
import { describeError } from "@/lib/errors";
import { useSubjectContext } from "@/lib/subjects/subject-context";
import { DocumentStatusBadge } from "@/components/documents/document-status-badge";
import { UploadDocumentButton } from "@/components/documents/upload-document-button";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { StateCard } from "@/components/shared/state-card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

// Spec §1/§3.4: no ingest push - poll while anything is still pending/
// processing, capped so an endlessly-stuck job doesn't poll forever.
const POLL_INTERVAL_MS = 2500;
const MAX_POLL_MS = 5 * 60 * 1000;

export default function DocumentsPage({ params }: { params: Promise<{ subjectId: string }> }) {
  const { subjectId } = use(params);
  const { canManage } = useSubjectContext();
  const queryClient = useQueryClient();
  const [pollStartedAt] = useState(() => Date.now());
  const [downloadingId, setDownloadingId] = useState<string | null>(null);

  const { data: documents, isLoading, isError, error } = useQuery({
    queryKey: queryKeys.documents(subjectId),
    queryFn: () => listDocuments(subjectId),
    refetchInterval: (query) => {
      const docs = query.state.data;
      if (!docs) return false;
      const stillProcessing = docs.some((d) => d.status === "pending" || d.status === "processing");
      if (!stillProcessing) return false;
      if (Date.now() - pollStartedAt > MAX_POLL_MS) return false;
      return POLL_INTERVAL_MS;
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (documentId: string) => deleteDocument(subjectId, documentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.documents(subjectId) });
      toast.success("Document deleted.");
    },
  });

  async function handleDownload(documentId: string, filename: string) {
    setDownloadingId(documentId);
    try {
      await downloadDocument(subjectId, documentId, filename);
    } catch (err) {
      toast.error(describeError(err));
    } finally {
      setDownloadingId(null);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {canManage && (
        <div className="flex items-center justify-end">
          <UploadDocumentButton subjectId={subjectId} />
        </div>
      )}

      {isLoading && (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      )}

      {isError && <p className="text-sm text-destructive">{describeError(error)}</p>}

      {documents && documents.length === 0 && (
        <StateCard
          icon={FileText}
          title="No documents yet"
          description={
            canManage
              ? "Upload one to ground the Tutor's answers - .txt, .pdf, .docx, .pptx, or .xlsx, up to 50MB."
              : "Nothing has been uploaded to this subject yet."
          }
        />
      )}

      {documents && documents.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Filename</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Chunks</TableHead>
              <TableHead className="w-24" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {documents.map((doc) => (
              <TableRow key={doc.id}>
                <TableCell className="font-medium">{doc.filename}</TableCell>
                <TableCell>
                  <div className="flex flex-col gap-0.5">
                    <DocumentStatusBadge status={doc.status} />
                    {doc.status === "failed" && doc.error && (
                      <span className="text-xs text-destructive">{doc.error}</span>
                    )}
                  </div>
                </TableCell>
                <TableCell className="text-muted-foreground">{doc.chunk_count}</TableCell>
                <TableCell>
                  <div className="flex justify-end gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      disabled={downloadingId === doc.id}
                      onClick={() => handleDownload(doc.id, doc.filename)}
                      title="Download original file"
                    >
                      <Download />
                    </Button>
                    {canManage && (
                      <ConfirmDialog
                        trigger={
                          <Button variant="ghost" size="icon" className="text-destructive hover:text-destructive">
                            <Trash2 />
                          </Button>
                        }
                        title={`Delete ${doc.filename}?`}
                        description="Removes it and its vector chunks. The underlying file is only removed if nothing else still references the same content."
                        onConfirm={() => deleteMutation.mutateAsync(doc.id)}
                      />
                    )}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
