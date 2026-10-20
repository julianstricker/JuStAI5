import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Group,
  Modal,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Textarea,
  Tooltip,
} from "@mantine/core";
import { IconEdit, IconPlus, IconSearch, IconTrash } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { type Key, useT } from "@/shared/i18n";

import { api, qs } from "@/shared/api";

import { PageHeader, fmtTime, useAction } from "../components/common";

export interface MemoryItem {
  id: string;
  kind: string;
  scope: string;
  owner_person_id: string | null;
  room_id: string | null;
  subject: string | null;
  predicate: string | null;
  content: string;
  value: Record<string, unknown>;
  provenance: string;
  confidence: number;
  importance: number;
  source: Record<string, unknown>;
  status: string;
  created_at: string;
  updated_at: string;
  score?: number | null;
}

const PROVENANCE: Record<string, { label: Key; color: string }> = {
  confirmed: { label: "mem.confirmed", color: "green" },
  extracted: { label: "mem.extracted", color: "blue" },
  observed: { label: "mem.observed", color: "teal" },
  inferred: { label: "mem.inferred", color: "orange" },
};

function Editor({
  item,
  people,
  onClose,
}: {
  item: MemoryItem | null;
  people: { id: string; name: string }[];
  onClose: () => void;
}) {
  const [content, setContent] = useState(item?.content ?? "");
  const t = useT();
  const [kind, setKind] = useState(item?.kind ?? "fact");
  const [scope, setScope] = useState(item?.scope ?? "shared");
  const [owner, setOwner] = useState<string | null>(
    item?.owner_person_id ?? null,
  );
  const [subject, setSubject] = useState(item?.subject ?? "");
  const [predicate, setPredicate] = useState(item?.predicate ?? "");
  const save = useAction(
    () => {
      const body = {
        content,
        kind,
        scope,
        owner_person_id: owner,
        subject: subject || null,
        predicate: predicate || null,
      };
      return item
        ? api.patch(`/api/memory/${item.id}`, body)
        : api.post("/api/memory", { ...body, provenance: "confirmed" });
    },
    { invalidate: [["memory"]], success: t("mem.saved") },
  );
  return (
    <Modal
      opened
      onClose={onClose}
      title={item ? t("mem.edit") : t("mem.new")}
      size="lg"
    >
      <Stack>
        <Textarea
          label={t("mem.content")}
          autosize
          minRows={2}
          value={content}
          onChange={(e) => setContent(e.currentTarget.value)}
        />
        <Group grow>
          <Select
            label={t("mem.kind")}
            data={["fact", "preference", "episode", "procedure", "note"]}
            value={kind}
            onChange={(v) => setKind(v ?? "fact")}
          />
          <Select
            label={t("mem.visibility")}
            data={[
              { value: "private", label: t("mem.private") },
              { value: "room", label: t("mem.room") },
              { value: "shared", label: t("mem.shared") },
              { value: "system", label: t("mem.system") },
            ]}
            value={scope}
            onChange={(v) => setScope(v ?? "shared")}
          />
        </Group>
        <Select
          label={t("mem.person")}
          clearable
          data={people.map((p) => ({ value: p.id, label: p.name }))}
          value={owner}
          onChange={setOwner}
        />
        <Group grow>
          <TextInput
            label={t("mem.subject")}
            value={subject}
            onChange={(e) => setSubject(e.currentTarget.value)}
          />
          <TextInput
            label={t("mem.predicate")}
            value={predicate}
            onChange={(e) => setPredicate(e.currentTarget.value)}
          />
        </Group>
        <Button
          onClick={async () => {
            await save.mutateAsync(undefined);
            onClose();
          }}
          disabled={!content}
        >
          {t("common.save")}
        </Button>
      </Stack>
    </Modal>
  );
}

export function MemoryPage() {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [person, setPerson] = useState<string | null>(null);
  const [kind, setKind] = useState<string | null>(null);
  const [editing, setEditing] = useState<MemoryItem | null | "new">(null);
  const t = useT();
  const people = useQuery({
    queryKey: ["people"],
    queryFn: () => api.get<{ id: string; name: string }[]>("/api/people"),
  });
  const items = useQuery({
    queryKey: ["memory", submitted, person, kind],
    queryFn: () =>
      api.get<MemoryItem[]>(
        `/api/memory${qs({ query: submitted, person_id: person, kind, limit: 200 })}`,
      ),
  });
  const del = useAction((id: string) => api.del(`/api/memory/${id}`), {
    invalidate: [["memory"]],
    success: t("mem.deleted"),
  });
  const consolidate = useAction(
    () =>
      api.post<{ merged: number; superseded: number }>(
        "/api/memory/consolidate",
      ),
    {
      invalidate: [["memory"]],
      success: (r) =>
        t("mem.consolidated", { merged: r.merged, superseded: r.superseded }),
    },
  );
  const name = (id: string | null) =>
    people.data?.find((p) => p.id === id)?.name ?? "–";

  return (
    <Stack>
      <PageHeader
        title={t("nav.memory")}
        description={t("mem.desc")}
        actions={
          <>
            <Button
              variant="default"
              onClick={() => consolidate.mutate(undefined)}
              loading={consolidate.isPending}
            >
              {t("mem.consolidate")}
            </Button>
            <Button
              leftSection={<IconPlus size={16} />}
              onClick={() => setEditing("new")}
            >
              {t("mem.add")}
            </Button>
          </>
        }
      />
      <Card withBorder>
        <Group>
          <TextInput
            style={{ flex: 1 }}
            leftSection={<IconSearch size={16} />}
            placeholder={t("mem.searchPlaceholder")}
            value={query}
            onChange={(e) => setQuery(e.currentTarget.value)}
            onKeyDown={(e) => e.key === "Enter" && setSubmitted(query)}
          />
          <Select
            placeholder={t("mem.person")}
            clearable
            data={(people.data ?? []).map((p) => ({
              value: p.id,
              label: p.name,
            }))}
            value={person}
            onChange={setPerson}
          />
          <Select
            placeholder={t("mem.kind")}
            clearable
            data={["fact", "preference", "episode", "procedure", "note"]}
            value={kind}
            onChange={setKind}
          />
          <Button onClick={() => setSubmitted(query)}>
            {t("common.search")}
          </Button>
        </Group>
      </Card>
      <Table striped highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t("mem.content")}</Table.Th>
            <Table.Th>{t("mem.person")}</Table.Th>
            <Table.Th>{t("mem.kindVisibility")}</Table.Th>
            <Table.Th>{t("mem.origin")}</Table.Th>
            <Table.Th>{t("mem.updated")}</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {items.data?.map((m) => (
            <Table.Tr key={m.id} opacity={m.status === "active" ? 1 : 0.5}>
              <Table.Td>
                <Text size="sm">{m.content}</Text>
                {m.subject && (
                  <Text size="xs" c="dimmed">
                    {m.subject} · {m.predicate}
                  </Text>
                )}
                {m.score !== undefined && m.score !== null && (
                  <Text size="xs" c="dimmed">
                    {t("mem.relevance", { v: m.score.toFixed(2) })}
                  </Text>
                )}
              </Table.Td>
              <Table.Td>{name(m.owner_person_id)}</Table.Td>
              <Table.Td>
                <Badge variant="outline" size="sm">
                  {m.kind}
                </Badge>{" "}
                <Badge variant="light" size="sm">
                  {m.scope}
                </Badge>
              </Table.Td>
              <Table.Td>
                <Tooltip label={JSON.stringify(m.source)}>
                  <Badge color={PROVENANCE[m.provenance]?.color ?? "gray"}>
                    {PROVENANCE[m.provenance]
                      ? t(PROVENANCE[m.provenance].label)
                      : m.provenance}
                  </Badge>
                </Tooltip>
                <Text size="xs" c="dimmed">
                  {t("mem.confidence", { p: (m.confidence * 100).toFixed(0) })}
                </Text>
              </Table.Td>
              <Table.Td>{fmtTime(m.updated_at)}</Table.Td>
              <Table.Td>
                <Group gap={4}>
                  <ActionIcon variant="subtle" onClick={() => setEditing(m)}>
                    <IconEdit size={16} />
                  </ActionIcon>
                  <ActionIcon
                    variant="subtle"
                    color="red"
                    onClick={() =>
                      confirm(t("mem.confirmDelete")) && del.mutate(m.id)
                    }
                  >
                    <IconTrash size={16} />
                  </ActionIcon>
                </Group>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      {items.data && !items.data.length && (
        <Text c="dimmed">{t("mem.none")}</Text>
      )}
      {editing && (
        <Editor
          item={editing === "new" ? null : editing}
          people={people.data ?? []}
          onClose={() => setEditing(null)}
        />
      )}
    </Stack>
  );
}
