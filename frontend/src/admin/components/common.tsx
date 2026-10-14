import { Badge, Group, Stack, Text, Title } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { ApiError } from "@/shared/api";

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <Group justify="space-between" align="flex-start" mb="md">
      <Stack gap={2}>
        <Title order={2}>{title}</Title>
        {description && (
          <Text c="dimmed" size="sm">
            {description}
          </Text>
        )}
      </Stack>
      {actions && <Group>{actions}</Group>}
    </Group>
  );
}

const STATUS_COLORS: Record<string, string> = {
  online: "green",
  running: "green",
  ok: "green",
  active: "green",
  displayed: "green",
  succeeded: "green",
  listening: "blue",
  speaking: "violet",
  processing: "orange",
  starting: "yellow",
  connecting: "yellow",
  degraded: "orange",
  pending: "yellow",
  offline: "red",
  failed: "red",
  error: "red",
  no_driver: "red",
  disabled: "gray",
  installed: "gray",
  unknown: "gray",
  ended: "gray",
};

export function StatusBadge({ status }: { status: string | null | undefined }) {
  const s = status ?? "unknown";
  return (
    <Badge color={STATUS_COLORS[s] ?? "gray"} variant="light">
      {s}
    </Badge>
  );
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return String(err);
}

export function notifyError(err: unknown) {
  notifications.show({ color: "red", title: "Fehler", message: errorMessage(err) });
}

export function notifyOk(message: string) {
  notifications.show({ color: "green", message });
}

/** Mutation that shows a toast and invalidates the given query keys. */
export function useAction<TArgs, TResult = unknown>(
  fn: (args: TArgs) => Promise<TResult>,
  opts: { invalidate?: string[][]; success?: string | ((r: TResult) => string) } = {},
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (result) => {
      for (const key of opts.invalidate ?? []) qc.invalidateQueries({ queryKey: key });
      if (opts.success) notifyOk(typeof opts.success === "function" ? opts.success(result) : opts.success);
    },
    onError: notifyError,
  });
}

export function fmtTime(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  const d = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  return d.toLocaleString("de-DE", { dateStyle: "short", timeStyle: "medium" });
}

export function Json({ value }: { value: unknown }) {
  return (
    <Text component="pre" size="xs" style={{ whiteSpace: "pre-wrap", wordBreak: "break-all", margin: 0 }}>
      {JSON.stringify(value, null, 2)}
    </Text>
  );
}
