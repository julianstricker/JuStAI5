import {
  Alert,
  Badge,
  Button,
  Card,
  Code,
  Group,
  JsonInput,
  Modal,
  ScrollArea,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { IconPlayerPlay, IconPlus } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/shared/api";
import { useT } from "@/shared/i18n";

import {
  PageHeader,
  StatusBadge,
  errorMessage,
  fmtTime,
  useAction,
} from "../components/common";

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
  trigger: {
    type: "event",
    event: "vision.person.recognized",
    match: { person_id: "<person-id>" },
  },
  conditions: [{ type: "time_window", start: "07:00", end: "22:00" }],
  actions: [
    {
      type: "assistant.invoke",
      instruction: "Greet the person by name.",
      room: "trigger",
      start_conversation: true,
    },
  ],
  options: { once: true, cooldown_s: 300 },
};

function Editor({
  automation,
  onClose,
}: {
  automation: Automation | null;
  onClose: () => void;
}) {
  const t = useT();
  const [name, setName] = useState(automation?.name ?? "");
  const [description, setDescription] = useState(automation?.description ?? "");
  const [definition, setDefinition] = useState(
    JSON.stringify(automation?.definition ?? EXAMPLE, null, 2),
  );
  const [error, setError] = useState<string | null>(null);
  const schema = useQuery({
    queryKey: ["automation-schema"],
    queryFn: () => api.get<Record<string, unknown>>("/api/automations/schema"),
  });
  const save = useAction(
    () => {
      const body = { name, description, definition: JSON.parse(definition) };
      return automation
        ? api.patch(`/api/automations/${automation.id}`, body)
        : api.post("/api/automations", body);
    },
    { invalidate: [["automations"]], success: t("auto.saved") },
  );
  return (
    <Modal
      opened
      onClose={onClose}
      title={automation ? automation.name : t("auto.new")}
      size="xl"
    >
      <SimpleGrid cols={{ base: 1, md: 2 }}>
        <Stack>
          <TextInput
            label={t("common.name")}
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
          />
          <TextInput
            label={t("common.description")}
            value={description}
            onChange={(e) => setDescription(e.currentTarget.value)}
          />
          <JsonInput
            label={t("auto.definition")}
            autosize
            minRows={16}
            value={definition}
            onChange={setDefinition}
            formatOnBlur
          />
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
            {t("common.save")}
          </Button>
        </Stack>
        <ScrollArea h={560}>
          <Title order={6}>{t("auto.blocks")}</Title>
          <Code block>{JSON.stringify(schema.data ?? {}, null, 2)}</Code>
        </ScrollArea>
      </SimpleGrid>
    </Modal>
  );
}

function Runs({ automation }: { automation: Automation }) {
  const runs = useQuery({
    queryKey: ["runs", automation.id],
    queryFn: () => api.get<Run[]>(`/api/automations/${automation.id}/runs`),
    refetchInterval: 5000,
  });
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
            <Table.Td>
              {r.error ?? r.log.map((l) => l.msg).join(" · ")}
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}

export function AutomationsPage() {
  const autos = useQuery({
    queryKey: ["automations"],
    queryFn: () => api.get<Automation[]>("/api/automations"),
    refetchInterval: 5000,
  });
  const [editing, setEditing] = useState<Automation | null | "new">(null);
  const t = useT();
  const [expanded, setExpanded] = useState<string | null>(null);
  const toggle = useAction(
    (a: Automation) =>
      api.patch(`/api/automations/${a.id}`, { enabled: !a.enabled }),
    { invalidate: [["automations"]] },
  );
  const run = useAction(
    (id: string) => api.post(`/api/automations/${id}/run`),
    { success: t("auto.testStarted"), invalidate: [["automations"]] },
  );
  const del = useAction((id: string) => api.del(`/api/automations/${id}`), {
    invalidate: [["automations"]],
    success: t("auto.deleted"),
  });

  return (
    <Stack>
      <PageHeader
        title={t("nav.automations")}
        description={t("auto.desc")}
        actions={
          <Button
            leftSection={<IconPlus size={16} />}
            onClick={() => setEditing("new")}
          >
            {t("auto.add")}
          </Button>
        }
      />
      {autos.data?.map((a) => (
        <Card key={a.id} withBorder>
          <Group justify="space-between">
            <Group gap="xs">
              <Switch checked={a.enabled} onChange={() => toggle.mutate(a)} />
              <Text fw={600}>{a.name}</Text>
              <Badge variant="light">
                {String(
                  (a.definition.trigger as { type?: string; event?: string })
                    ?.event ??
                    (a.definition.trigger as { type?: string })?.type,
                )}
              </Badge>
              <Badge variant="outline">
                {t("auto.by", { who: a.created_by })}
              </Badge>
              {!!a.state.run_count && (
                <Text size="xs" c="dimmed">
                  {t("auto.runs", {
                    n: a.state.run_count,
                    when: fmtTime(a.state.last_run_at),
                  })}
                </Text>
              )}
            </Group>
            <Group gap="xs">
              <Button
                size="xs"
                variant="light"
                leftSection={<IconPlayerPlay size={14} />}
                onClick={() => run.mutate(a.id)}
              >
                {t("auto.test")}
              </Button>
              <Button
                size="xs"
                variant="subtle"
                onClick={() => setExpanded(expanded === a.id ? null : a.id)}
              >
                {t("auto.log")}
              </Button>
              <Button size="xs" variant="subtle" onClick={() => setEditing(a)}>
                {t("common.edit")}
              </Button>
              <Button
                size="xs"
                variant="subtle"
                color="red"
                onClick={() =>
                  confirm(t("auto.confirmDelete")) && del.mutate(a.id)
                }
              >
                {t("common.delete")}
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
      {autos.data && !autos.data.length && (
        <Text c="dimmed">{t("auto.none")}</Text>
      )}
      {editing && (
        <Editor
          automation={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
        />
      )}
    </Stack>
  );
}
