import {
  Alert,
  Badge,
  Button,
  Card,
  Code,
  Group,
  JsonInput,
  Modal,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/shared/api";
import { rich, useT } from "@/shared/i18n";
import type { Room } from "@/shared/types";

import {
  PageHeader,
  StatusBadge,
  fmtTime,
  useAction,
} from "../components/common";

interface DisplayInfo {
  device_id: string;
  name: string;
  room_id: string | null;
  status: string;
  connected: boolean;
  capabilities: string[];
  presentation: { id: string; status: string; title: string | null } | null;
}
interface Pending {
  code: string;
  user_agent: string;
  capabilities: string[];
  since: string;
}
interface Presentation {
  id: string;
  display_device_id: string;
  room_id: string | null;
  status: string;
  created_at: string;
  displayed_at: string | null;
  error: string | null;
  document: { title?: string };
}

const TEST_DOC = {
  title: "JuStAI5 test display",
  layout: "dashboard",
  components: [
    { type: "heading", text: "Hello from the assistant" },
    {
      type: "stat",
      label: "Temperature",
      value: 21.5,
      unit: "°C",
      trend: "up",
    },
    { type: "clock" },
    {
      type: "chart",
      kind: "line",
      title: "Example",
      series: [
        {
          name: "Values",
          points: [
            ["Mo", 3],
            ["Di", 5],
            ["Mi", 4],
            ["Do", 7],
          ],
        },
      ],
    },
  ],
  duration_s: 60,
};

function PairModal({
  pending,
  onClose,
}: {
  pending: Pending;
  onClose: () => void;
}) {
  const rooms = useQuery({
    queryKey: ["rooms"],
    queryFn: () => api.get<Room[]>("/api/rooms"),
  });
  const [name, setName] = useState("Display");
  const t = useT();
  const [room, setRoom] = useState<string | null>(null);
  const approve = useAction(
    () =>
      api.post(`/api/displays/pairing/${pending.code}/approve`, {
        name,
        room_id: room,
      }),
    {
      invalidate: [["displays"], ["display-pending"], ["devices"]],
      success: t("disp.paired"),
    },
  );
  return (
    <Modal
      opened
      onClose={onClose}
      title={t("disp.pairTitle", { code: pending.code })}
    >
      <Stack>
        <Text size="xs" c="dimmed">
          {pending.user_agent}
        </Text>
        <TextInput
          label={t("common.name")}
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
        />
        <Select
          label={t("common.room")}
          data={(rooms.data ?? []).map((r) => ({ value: r.id, label: r.name }))}
          value={room}
          onChange={setRoom}
        />
        <Button
          disabled={!room}
          onClick={async () => {
            await approve.mutateAsync(undefined);
            onClose();
          }}
        >
          {t("disp.pair")}
        </Button>
      </Stack>
    </Modal>
  );
}

export function DisplaysPage() {
  const displays = useQuery({
    queryKey: ["displays"],
    queryFn: () => api.get<DisplayInfo[]>("/api/displays"),
    refetchInterval: 3000,
  });
  const pending = useQuery({
    queryKey: ["display-pending"],
    queryFn: () => api.get<Pending[]>("/api/displays/pending"),
    refetchInterval: 3000,
  });
  const presentations = useQuery({
    queryKey: ["presentations"],
    queryFn: () => api.get<Presentation[]>("/api/displays/presentations"),
    refetchInterval: 5000,
  });
  const rooms = useQuery({
    queryKey: ["rooms"],
    queryFn: () => api.get<Room[]>("/api/rooms"),
  });
  const [pairing, setPairing] = useState<Pending | null>(null);
  const t = useT();
  const [doc, setDoc] = useState(JSON.stringify(TEST_DOC, null, 2));
  const [target, setTarget] = useState<string | null>(null);
  const test = useAction(
    (id: string) =>
      api.post(`/api/displays/${id}/present`, { document: JSON.parse(doc) }),
    {
      invalidate: [["presentations"]],
      success: t("disp.sent"),
    },
  );
  const close = useAction(
    ({ device, pres }: { device: string; pres: string }) =>
      api.post(`/api/displays/${device}/close/${pres}`),
    {
      invalidate: [["presentations"], ["displays"]],
    },
  );
  const roomName = (id: string | null) =>
    rooms.data?.find((r) => r.id === id)?.name ?? "–";
  const url = `${location.origin}/display`;

  return (
    <Stack>
      <PageHeader title={t("disp.title")} description={t("disp.desc")} />
      <Alert color="blue">
        {rich(t("disp.hint"), {
          url: <Code>{url}</Code>,
          app: <Code>{`https://${location.hostname}:8443/app`}</Code>,
        })}
      </Alert>
      {!!pending.data?.length && (
        <Card withBorder>
          <Title order={5} mb="xs">
            {t("disp.waiting")}
          </Title>
          {pending.data.map((p) => (
            <Group key={p.code} justify="space-between">
              <Text>
                {rich(t("disp.code"), { code: <b>{p.code}</b> })} ·{" "}
                {p.user_agent.slice(0, 80)}
              </Text>
              <Button size="xs" onClick={() => setPairing(p)}>
                {t("disp.pair")}
              </Button>
            </Group>
          ))}
        </Card>
      )}
      <SimpleGrid cols={{ base: 1, md: 2 }}>
        {displays.data?.map((d) => (
          <Card key={d.device_id} withBorder>
            <Group justify="space-between">
              <Title order={5}>{d.name}</Title>
              <Group gap={4}>
                <StatusBadge status={d.connected ? "online" : "offline"} />
                <Badge variant="light">{roomName(d.room_id)}</Badge>
              </Group>
            </Group>
            <Group gap={4} mt="xs">
              {d.capabilities.map((c) => (
                <Badge key={c} size="xs" variant="outline">
                  {c}
                </Badge>
              ))}
            </Group>
            {d.presentation && (
              <Group mt="xs">
                <Text size="sm">
                  {t("disp.showing", {
                    title: d.presentation.title ?? d.presentation.id,
                  })}{" "}
                  <StatusBadge status={d.presentation.status} />
                </Text>
                <Button
                  size="compact-xs"
                  variant="subtle"
                  onClick={() =>
                    close.mutate({
                      device: d.device_id,
                      pres: d.presentation!.id,
                    })
                  }
                >
                  {t("common.close")}
                </Button>
              </Group>
            )}
          </Card>
        ))}
      </SimpleGrid>
      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        <Card withBorder>
          <Stack>
            <Title order={5}>{t("disp.test")}</Title>
            <Select
              label={t("disp.display")}
              data={(displays.data ?? []).map((d) => ({
                value: d.device_id,
                label: d.name,
              }))}
              value={target}
              onChange={setTarget}
            />
            <JsonInput
              autosize
              minRows={12}
              value={doc}
              onChange={setDoc}
              formatOnBlur
            />
            <Button
              disabled={!target}
              onClick={() => target && test.mutate(target)}
              loading={test.isPending}
            >
              {t("common.send")}
            </Button>
          </Stack>
        </Card>
        <Card withBorder>
          <Title order={5} mb="xs">
            {t("disp.presentations")}
          </Title>
          <Table fz="xs">
            <Table.Tbody>
              {presentations.data?.map((p) => (
                <Table.Tr key={p.id}>
                  <Table.Td>{fmtTime(p.created_at)}</Table.Td>
                  <Table.Td>{p.document.title ?? p.id}</Table.Td>
                  <Table.Td>{roomName(p.room_id)}</Table.Td>
                  <Table.Td>
                    <StatusBadge status={p.status} />
                  </Table.Td>
                  <Table.Td>{p.error}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Card>
      </SimpleGrid>
      {pairing && (
        <PairModal pending={pairing} onClose={() => setPairing(null)} />
      )}
    </Stack>
  );
}
