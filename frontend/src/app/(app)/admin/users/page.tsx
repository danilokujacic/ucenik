"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, MoreHorizontal } from "lucide-react";
import { listUsers, deleteUser } from "@/lib/api/admin-users";
import { queryKeys } from "@/lib/query/keys";
import { describeError } from "@/lib/errors";
import { useAuth } from "@/lib/auth/auth-context";
import { RequireRole } from "@/components/auth/guards";
import { UserFormDialog } from "@/components/admin/user-form-dialog";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

function AdminUsersPage() {
  const { user: me } = useAuth();
  const queryClient = useQueryClient();
  const { data: users, isLoading, isError, error } = useQuery({
    queryKey: queryKeys.adminUsers(),
    queryFn: listUsers,
  });

  const deleteMutation = useMutation({
    mutationFn: (userId: string) => deleteUser(userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.adminUsers() });
      toast.success("User deleted.");
    },
  });

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Users</h1>
          <p className="text-sm text-muted-foreground">
            The only way to create an account - there&apos;s no self-service signup.
          </p>
        </div>
        <UserFormDialog
          trigger={
            <Button>
              <Plus /> Create user
            </Button>
          }
        />
      </div>

      {isLoading && (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      )}

      {isError && <p className="text-sm text-destructive">{describeError(error)}</p>}

      {users && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Role</TableHead>
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {users.map((u) => (
              <TableRow key={u.id}>
                <TableCell className="font-medium">{u.full_name}</TableCell>
                <TableCell className="text-muted-foreground">{u.email}</TableCell>
                <TableCell>
                  <Badge variant="outline" className="capitalize">
                    {u.role}
                  </Badge>
                </TableCell>
                <TableCell>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="ghost" size="icon">
                        <MoreHorizontal />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <UserFormDialog
                        user={u}
                        trigger={
                          <DropdownMenuItem onSelect={(e) => e.preventDefault()}>Edit</DropdownMenuItem>
                        }
                      />
                      <ConfirmDialog
                        trigger={
                          <DropdownMenuItem
                            variant="destructive"
                            disabled={u.id === me?.id}
                            onSelect={(e) => e.preventDefault()}
                          >
                            Delete
                          </DropdownMenuItem>
                        }
                        title={`Delete ${u.full_name}?`}
                        description="This revokes their sessions immediately. It does not delete content they own (subjects, documents, chat) - that's a known gap, not something silently handled."
                        onConfirm={() => deleteMutation.mutateAsync(u.id)}
                      />
                    </DropdownMenuContent>
                  </DropdownMenu>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}

export default function Page() {
  return (
    <RequireRole roles={["admin"]}>
      <AdminUsersPage />
    </RequireRole>
  );
}
