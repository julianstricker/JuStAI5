import { Alert, Badge, Button, Card, Code, Group, JsonInput, Modal, ScrollArea, SimpleGrid, Stack, Switch, Table, Text, TextInput, Title } from "@mantine/core";
import { IconPlayerPlay, IconPlus } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/shared/api";

import { PageHeader, StatusBadge, errorMessage, fmtTime, useAction } from "../components/common";

interface Automation {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  definition: Record<string, unknown>;
  created_by: string;
  state: { run_count?: number; last_run_at?: string; cooldown_until?: string };
  updated_at: string;
}

interface Run {
  id: string;
  event_id: string | null;
  status: string;
  attempts: number;
  started_at: string;
  finished_at: string | null;
  error: string | null;
  log: { t: string; msg: string }[];
}

const EXAMPLE = {
  trigger: { type: "event", event: "vision.person.recognized", match: { person_id: "<person-id>" } },
  conditions: [{ type: "time_window", start: "07:00", end: "22:00" }],
  actions: [{ type: "assistant.invoke", instruction: "Begrüße die Person mit ihrem Namen.", room: "trigger", start_conversation: true }],
  options: { once: true, cooldown_s: 300 },
};

function Editor({ automation, onClose }: { automation: Automation | null; onClose: () => void }) {
  const [name, setName] = useState(automation?.name ?? "");
  const [description, setDescription] = useState(automation?.description ?? "");
  const [definition, setDefinition] = useState(JSON.stringify(automation?.definition ?? EXAMPLE, null, 2));
  const [error, setError] = useState<string | null>(null);
  const schema = useQuery({ queryKey: ["automation-schema"], queryFn: () => api.get<Record<string, unknown>>("/api/automations/schema") });
  const save = useAction(
    () => {
      const body = { name, description, definition: JSON.parse(definition) };
      return automation ? api.patch(`/api/automations/${automation.id}`, body) : api.post("/api/automations", body);
    },
    { invalidate: [["automations"]], success: "Automation gespeichert" },
  );
  return (
    <Modal opened onClose={onClose} title={automation ? automation.name : "Neue Automation"} size="xl">
      <SimpleGrid cols={{ base: 1, md: 2 }}>
        <Stack>
          <TextInput label="Name" value={name} onChange={(e) => setName(e.currentTarget.value)} />
          <TextInput label="Beschreibung" value={description} onChange={(e) => setDescription(e.currentTarget.value)} />
          <JsonInput label="Definition (Trigger, Bedingungen, Aktionen, Optionen)" autosize minRows={16} value={definition} onChange={setDefinition} formatOnBlur />
          {error && <Alert color="red">{error}</Alert>}
          <Button
            onClick={async () => {
              try {
                setError(null);
                await save.mutateAsync(undefined);
                onClose();
              } catch (err) {
                setError(errorMessage(err));
              }
            }}
          >
            Speichern
          </Button>
        </Stack>
        <ScrollArea h={560}>
          <Title order={6}>Bausteine</Title>
          <Code block>{JSON.stringify(schema.data ?? {}, null, 2)}</Code>
        </ScrollArea>
      </SimpleGrid>
    </Modal>
  );
}

function Runs({ automation }: { automation: Automation }) {
  const runs = useQuery({ queryKey: ["runs", automation.id], queryFn: () => api.get<Run[]>(`/api/automations/${automation.id}/runs`), refetchInterval: 5000 });
  return (
    <Table fz="xs">
      <Table.Tbody>
        {runs.data?.map((r) => (
          <Table.Tr key={r.id}>
            <Table.Td>{fmtTime(r.started_at)}</Table.Td>
            <Table.Td>
              <StatusBadge status={r.status} />
            </Table.Td>
            <Table.Td>{r.attempts}×</Table.Td>
            <Table.Td>{r.error ?? r.log.map((l) => l.msg).join(" · ")}</Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}

export function AutomationsPage() {
  const autos = useQuery({ queryKey: ["automations"], queryFn: () => api.get<Automation[]>("/api/automations"), refetchInterval: 5000 });
  const [editing, setEditing] = useState<Automation | null | "new">(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const toggle = useAction((a: Automation) => api.patch(`/api/automations/${a.id}`, { enabled: !a.enabled }), { invalidate: [["automations"]] });
  const run = useAction((id: string) => api.post(`/api/automations/${id}/run`), { success: "Testlauf gestartet", invalidate: [["automations"]] });
  const del = useAction((id: string) => api.del(`/api/automations/${id}`), { invalidate: [["automations"]], success: "Automation gelöscht" });

  return (
    <Stack>
      <PageHeader
        title="Automationen"
        description="Regeln aus Trigger, Bedingungen und Aktionen. Der Assistent kann sie auch aus Sprache anlegen."
        actions={
          <Button leftSection={<IconPlus size={16} />} onClick={() => setEditing("new")}>
            Automation
          </Button>
        }
      />
      {autos.data?.map((a) => (
        <Card key={a.id} withBorder>
          <Group justify="space-between">
            <Group gap="xs">
              <Switch checked={a.enabled} onChange={() => toggle.mutate(a)} />
              <Text fw={600}>{a.name}</Text>
              <Badge variant="light">{String((a.definition.trigger as { type?: string; event?: string })?.event ?? (a.definition.trigger as { type?: string })?.type)}</Badge>
              <Badge variant="outline">von {a.created_by}</Badge>
              {!!a.state.run_count && <Text size="xs" c="dimmed">{a.state.run_count}× ausgeführt, zuletzt {fmtTime(a.state.last_run_at)}</Text>}
            </Group>
            <Group gap="xs">
              <Button size="xs" variant="light" leftSection={<IconPlayerPlay size={14} />} onClick={() => run.mutate(a.id)}>
                Test
              </Button>
              <Button size="xs" variant="subtle" onClick={() => setExpanded(expanded === a.id ? null : a.id)}>
                Protokoll
              </Button>
              <Button size="xs" variant="subtle" onClick={() => setEditing(a)}>
                Bearbeiten
              </Button>
              <Button size="xs" variant="subtle" color="red" onClick={() => confirm("Automation löschen?") && del.mutate(a.id)}>
                Löschen
              </Button>
            </Group>
          </Group>
          {a.description && (
            <Text size="sm" c="dimmed">
              {a.description}
            </Text>
          )}
          {expanded === a.id && (
            <Stack mt="sm">
              <Code block>{JSON.stringify(a.definition, null, 2)}</Code>
              <Runs automation={a} />
            </Stack>
          )}
        </Card>
      ))}
      {autos.data && !autos.data.length && <Text c="dimmed">Noch keine Automationen.</Text>}
      {editing && <Editor automation={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </Stack>
  );
}
