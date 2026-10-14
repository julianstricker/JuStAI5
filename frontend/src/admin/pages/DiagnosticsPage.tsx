import { Badge, Button, Card, Code, Group, JsonInput, ScrollArea, Select, SimpleGrid, Stack, Table, Tabs, Text, TextInput, Title } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/shared/api";
import { useLiveEvents } from "@/shared/live";
import type { Room, ToolInfo } from "@/shared/types";

import { Json, PageHeader, fmtTime, notifyError, useAction } from "../components/common";

interface CatalogEntry {
  type: string;
  description: string;
  durable: boolean;
  owner: string;
}
interface Execution {
  id: string;
  tool: string;
  origin: string;
  status: string;
  params: Record<string, unknown>;
  error: string | null;
  duration_ms: number;
  created_at: string;
}
interface AuditRow {
  ts: string;
  actor: string;
  action: string;
  target: string | null;
  detail: Record<string, unknown>;
}

function LiveEvents() {
  const [filter, setFilter] = useState("");
  const events = useLiveEvents(300);
  const shown = events.filter((e) => !filter || e.type.includes(filter));
  return (
    <Card withBorder>
      <Group mb="xs">
        <TextInput placeholder="Filter (z. B. vision.)" value={filter} onChange={(e) => setFilter(e.currentTarget.value)} />
        <Text size="xs" c="dimmed">
          {shown.length} Ereignisse
        </Text>
      </Group>
      <ScrollArea h={500}>
        <Table fz="xs">
          <Table.Tbody>
            {shown.map((e) => (
              <Table.Tr key={e.id}>
                <Table.Td style={{ whiteSpace: "nowrap" }}>{fmtTime(e.timestamp)}</Table.Td>
                <Table.Td>
                  <Code>{e.type}</Code>
                  {e.hop > 0 && <Badge size="xs">hop {e.hop}</Badge>}
                </Table.Td>
                <Table.Td style={{ wordBreak: "break-all" }}>{JSON.stringify(e.payload)}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </ScrollArea>
    </Card>
  );
}

function ManualEvent() {
  const catalog = useQuery({ queryKey: ["event-catalog"], queryFn: () => api.get<CatalogEntry[]>("/api/events/catalog") });
  const rooms = useQuery({ queryKey: ["rooms"], queryFn: () => api.get<Room[]>("/api/rooms") });
  const [type, setType] = useState<string | null>("manual.test");
  const [room, setRoom] = useState<string | null>(null);
  const [payload, setPayload] = useState("{}");
  const send = useAction(() => api.post<{ accepted: boolean }>("/api/events", { type, room_id: room, payload: JSON.parse(payload) }), {
    success: (r) => (r.accepted ? "Ereignis veröffentlicht" : "Ereignis verworfen (Duplikat/Schleife)"),
  });
  return (
    <Card withBorder>
      <Stack>
        <Title order={5}>Ereignis manuell auslösen</Title>
        <Select searchable label="Typ" data={(catalog.data ?? []).map((c) => ({ value: c.type, label: `${c.type} – ${c.description}` }))} value={type} onChange={setType} />
        <Select label="Raum" clearable data={(rooms.data ?? []).map((r) => ({ value: r.id, label: r.name }))} value={room} onChange={setRoom} />
        <JsonInput label="Payload" autosize minRows={4} value={payload} onChange={setPayload} formatOnBlur />
        <Button onClick={() => send.mutate(undefined)} loading={send.isPending}>
          Auslösen
        </Button>
      </Stack>
    </Card>
  );
}

function ToolTester() {
  const tools = useQuery({ queryKey: ["tools"], queryFn: () => api.get<ToolInfo[]>("/api/tools") });
  const rooms = useQuery({ queryKey: ["rooms"], queryFn: () => api.get<Room[]>("/api/rooms") });
  const [name, setName] = useState<string | null>(null);
  const [room, setRoom] = useState<string | null>(null);
  const [args, setArgs] = useState("{}");
  const [result, setResult] = useState<unknown>(null);
  const tool = tools.data?.find((t) => t.name === name);
  const run = async () => {
    try {
      setResult(await api.post(`/api/tools/${name}/execute`, { args: JSON.parse(args), room_id: room }));
    } catch (err) {
      notifyError(err);
    }
  };
  return (
    <Card withBorder>
      <Stack>
        <Title order={5}>Tool-Aufruf testen</Title>
        <Select searchable label="Tool" data={(tools.data ?? []).map((t) => ({ value: t.name, label: t.name }))} value={name} onChange={setName} />
        {tool && (
          <Text size="xs" c="dimmed">
            {tool.description} · Berechtigungen: {tool.permissions.join(", ") || "keine"} · {tool.side_effect}
            {tool.requires_confirmation && " · benötigt Bestätigung"}
          </Text>
        )}
        <Select label="Raumkontext" clearable data={(rooms.data ?? []).map((r) => ({ value: r.id, label: r.name }))} value={room} onChange={setRoom} />
        <JsonInput label="Argumente" autosize minRows={3} value={args} onChange={setArgs} formatOnBlur />
        {tool && (
          <Text size="xs">
            Schema: <Code block>{JSON.stringify(tool.parameters, null, 1)}</Code>
          </Text>
        )}
        <Button onClick={run} disabled={!name}>
          Ausführen
        </Button>
        {result !== null && <Json value={result} />}
      </Stack>
    </Card>
  );
}

export function DiagnosticsPage() {
  const status = useQuery({ queryKey: ["status-full"], queryFn: () => api.get<any>("/api/system/status"), refetchInterval: 5000 });
  const executions = useQuery({ queryKey: ["executions"], queryFn: () => api.get<Execution[]>("/api/tools/executions"), refetchInterval: 5000 });
  const audit = useQuery({ queryKey: ["audit"], queryFn: () => api.get<AuditRow[]>("/api/audit") });
  return (
    <Stack>
      <PageHeader title="Diagnose" description="Ereignisse, Tool-Aufrufe, Hintergrund-Tasks und Audit-Log" />
      <Tabs defaultValue="events">
        <Tabs.List>
          <Tabs.Tab value="events">Ereignisse</Tabs.Tab>
          <Tabs.Tab value="tools">Tools</Tabs.Tab>
          <Tabs.Tab value="tasks">Tasks & Bus</Tabs.Tab>
          <Tabs.Tab value="audit">Audit-Log</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="events" pt="md">
          <SimpleGrid cols={{ base: 1, xl: 2 }}>
            <LiveEvents />
            <ManualEvent />
          </SimpleGrid>
        </Tabs.Panel>
        <Tabs.Panel value="tools" pt="md">
          <SimpleGrid cols={{ base: 1, xl: 2 }}>
            <ToolTester />
            <Card withBorder>
              <Title order={5} mb="xs">
                Letzte Ausführungen
              </Title>
              <ScrollArea h={500}>
                <Table fz="xs">
                  <Table.Tbody>
                    {executions.data?.map((x) => (
                      <Table.Tr key={x.id}>
                        <Table.Td>{fmtTime(x.created_at)}</Table.Td>
                        <Table.Td>{x.tool}</Table.Td>
                        <Table.Td>{x.origin}</Table.Td>
                        <Table.Td>
                          <Badge size="xs" color={x.status === "ok" ? "green" : "red"}>
                            {x.status}
                          </Badge>
                        </Table.Td>
                        <Table.Td>{x.duration_ms} ms</Table.Td>
                        <Table.Td>{x.error}</Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </ScrollArea>
            </Card>
          </SimpleGrid>
        </Tabs.Panel>
        <Tabs.Panel value="tasks" pt="md">
          <SimpleGrid cols={{ base: 1, xl: 2 }}>
            <Card withBorder>
              <Title order={5} mb="xs">
                Überwachte Hintergrund-Tasks
              </Title>
              <Table fz="xs">
                <Table.Tbody>
                  {status.data?.tasks?.map((t: any) => (
                    <Table.Tr key={t.name}>
                      <Table.Td>{t.name}</Table.Td>
                      <Table.Td>{t.running ? "läuft" : "gestoppt"}</Table.Td>
                      <Table.Td>{t.restarts} Neustarts</Table.Td>
                      <Table.Td>{t.last_error}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Card>
            <Card withBorder>
              <Title order={5} mb="xs">
                Event-Bus
              </Title>
              <Json value={status.data?.events} />
            </Card>
          </SimpleGrid>
        </Tabs.Panel>
        <Tabs.Panel value="audit" pt="md">
          <Table fz="xs" striped>
            <Table.Tbody>
              {audit.data?.map((a, i) => (
                <Table.Tr key={i}>
                  <Table.Td>{fmtTime(a.ts)}</Table.Td>
                  <Table.Td>{a.actor}</Table.Td>
                  <Table.Td>{a.action}</Table.Td>
                  <Table.Td>{a.target}</Table.Td>
                  <Table.Td>{JSON.stringify(a.detail)}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
