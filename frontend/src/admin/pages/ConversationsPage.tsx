import { Badge, Button, Card, Group, ScrollArea, Select, SimpleGrid, Stack, Table, Tabs, Text, TextInput, Title } from "@mantine/core";
import { IconSend } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/shared/api";
import type { ActiveSession, Room } from "@/shared/types";

import { PageHeader, StatusBadge, fmtTime, notifyError, useAction } from "../components/common";

interface HistoryRow {
  id: string;
  endpoint_id: string | null;
  room_id: string | null;
  person_id: string | null;
  trigger: string;
  mode: string;
  language: string | null;
  started_at: string;
  ended_at: string | null;
  end_reason: string | null;
}

interface Turn {
  role: string;
  text: string;
  created_at: string;
  meta: Record<string, unknown>;
}

function Chat() {
  const rooms = useQuery({ queryKey: ["rooms"], queryFn: () => api.get<Room[]>("/api/rooms") });
  const [room, setRoom] = useState<string | null>(null);
  const [session, setSession] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [lines, setLines] = useState<{ role: string; text: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const send = async () => {
    if (!text.trim()) return;
    const msg = text;
    setText("");
    setLines((l) => [...l, { role: "user", text: msg }]);
    setBusy(true);
    try {
      const r = await api.post<{ session_id: string; answer: string }>("/api/conversations/ask", { text: msg, session_id: session, room_id: room });
      setSession(r.session_id);
      setLines((l) => [...l, { role: "assistant", text: r.answer }]);
    } catch (err) {
      notifyError(err);
      setSession(null);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card withBorder>
      <Stack>
        <Group>
          <Select
            label="Raumkontext"
            placeholder="ohne Raum"
            clearable
            data={(rooms.data ?? []).map((r) => ({ value: r.id, label: r.name }))}
            value={room}
            onChange={(v) => {
              setRoom(v);
              setSession(null);
            }}
          />
          <Button variant="subtle" mt="lg" onClick={() => (setSession(null), setLines([]))}>
            Neues Gespräch
          </Button>
        </Group>
        <ScrollArea h={360}>
          <Stack gap="xs">
            {lines.map((l, i) => (
              <Text key={i} c={l.role === "user" ? undefined : "indigo"}>
                <b>{l.role === "user" ? "Du" : "Assistent"}:</b> {l.text}
              </Text>
            ))}
          </Stack>
        </ScrollArea>
        <Group>
          <TextInput
            style={{ flex: 1 }}
            placeholder="Nachricht an den Assistenten …"
            value={text}
            onChange={(e) => setText(e.currentTarget.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
          />
          <Button onClick={send} loading={busy} leftSection={<IconSend size={16} />}>
            Senden
          </Button>
        </Group>
        <Text size="xs" c="dimmed">
          Text-Gespräche nutzen dieselben Tools und dasselbe Gedächtnis wie Sprachgespräche (Pipeline-Modus).
        </Text>
      </Stack>
    </Card>
  );
}

export function ConversationsPage() {
  const active = useQuery({ queryKey: ["sessions"], queryFn: () => api.get<ActiveSession[]>("/api/conversations/active"), refetchInterval: 1500 });
  const history = useQuery({ queryKey: ["session-history"], queryFn: () => api.get<HistoryRow[]>("/api/conversations/history?limit=100"), refetchInterval: 10000 });
  const rooms = useQuery({ queryKey: ["rooms"], queryFn: () => api.get<Room[]>("/api/rooms") });
  const [selected, setSelected] = useState<string | null>(null);
  const turns = useQuery({ queryKey: ["turns", selected], queryFn: () => api.get<Turn[]>(`/api/conversations/${selected}/turns`), enabled: !!selected });
  const end = useAction((id: string) => api.post(`/api/conversations/${id}/end`), { invalidate: [["sessions"]] });
  const roomName = (id: string | null) => rooms.data?.find((r) => r.id === id)?.name ?? "–";

  return (
    <Stack>
      <PageHeader title="Gespräche" description="Laufende Sessions, Verlauf mit Transkripten und Text-Chat" />
      <Tabs defaultValue="live">
        <Tabs.List>
          <Tabs.Tab value="live">Live</Tabs.Tab>
          <Tabs.Tab value="history">Verlauf</Tabs.Tab>
          <Tabs.Tab value="chat">Text-Chat</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="live" pt="md">
          <SimpleGrid cols={{ base: 1, lg: 2 }}>
            {active.data?.map((s) => (
              <Card key={s.id} withBorder>
                <Group justify="space-between">
                  <Group gap="xs">
                    <StatusBadge status={s.state} />
                    <Text fw={600}>{s.room ?? "Text"}</Text>
                    <Badge variant="outline">{s.mode}</Badge>
                    <Badge variant="light">{s.trigger}</Badge>
                    {s.person && <Badge color="teal">{s.person}</Badge>}
                  </Group>
                  <Button size="xs" color="red" variant="light" onClick={() => end.mutate(s.id)}>
                    Beenden
                  </Button>
                </Group>
                <Stack gap={4} mt="sm">
                  {s.transcript.map((t, i) => (
                    <Text key={i} size="sm" c={t.role === "user" ? undefined : "indigo"}>
                      <b>{t.role === "user" ? "Benutzer" : "Assistent"}:</b> {t.text}
                    </Text>
                  ))}
                </Stack>
              </Card>
            ))}
          </SimpleGrid>
          {!active.data?.length && <Text c="dimmed">Kein aktives Gespräch.</Text>}
        </Tabs.Panel>
        <Tabs.Panel value="history" pt="md">
          <SimpleGrid cols={{ base: 1, lg: 2 }}>
            <Table highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Start</Table.Th>
                  <Table.Th>Raum</Table.Th>
                  <Table.Th>Auslöser</Table.Th>
                  <Table.Th>Ende</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {history.data?.map((h) => (
                  <Table.Tr key={h.id} onClick={() => setSelected(h.id)} style={{ cursor: "pointer" }} bg={selected === h.id ? "var(--mantine-color-indigo-light)" : undefined}>
                    <Table.Td>{fmtTime(h.started_at)}</Table.Td>
                    <Table.Td>{roomName(h.room_id)}</Table.Td>
                    <Table.Td>
                      {h.trigger} / {h.mode}
                    </Table.Td>
                    <Table.Td>{h.end_reason ?? "läuft"}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
            <Card withBorder>
              <Title order={5} mb="xs">
                Transkript
              </Title>
              {turns.data?.map((t, i) => (
                <Text key={i} size="sm" c={t.role === "user" ? undefined : t.role === "tool" ? "dimmed" : "indigo"}>
                  <b>{t.role}:</b> {t.text || JSON.stringify(t.meta)}
                </Text>
              ))}
              {!selected && <Text c="dimmed">Gespräch auswählen.</Text>}
            </Card>
          </SimpleGrid>
        </Tabs.Panel>
        <Tabs.Panel value="chat" pt="md">
          <Chat />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
