import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Group,
  Image,
  Modal,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Text,
  TextInput,
  Textarea,
  Title,
} from "@mantine/core";
import {
  IconDownload,
  IconFaceId,
  IconPlus,
  IconTrash,
} from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { useT } from "@/shared/i18n";

import { api } from "@/shared/api";
import type { Device } from "@/shared/types";

import {
  PageHeader,
  fmtTime,
  notifyError,
  useAction,
} from "../components/common";

interface Person {
  id: string;
  name: string;
  kind: "person" | "pet";
  species: string | null;
  notes: string;
  biometric_consent: boolean;
  biometric_consent_at: string | null;
  recognition_enabled: boolean;
  face_count: number;
  voice_count?: number;
  last_seen: { at: string; camera: string | null; room: string | null } | null;
}

interface Face {
  id: string;
  quality: Record<string, number>;
  source: string;
  created_at: string;
  has_thumbnail: boolean;
}

function PersonModal({
  person,
  onClose,
}: {
  person: Person | null;
  onClose: () => void;
}) {
  const [name, setName] = useState(person?.name ?? "");
  const [kind, setKind] = useState<string>(person?.kind ?? "person");
  const t = useT();
  const [species, setSpecies] = useState(person?.species ?? "");
  const [notes, setNotes] = useState(person?.notes ?? "");
  const [recognition, setRecognition] = useState(
    person?.recognition_enabled ?? true,
  );
  const save = useAction(
    () => {
      const body = {
        name,
        kind,
        species: species || null,
        notes,
        recognition_enabled: recognition,
      };
      return person
        ? api.patch(`/api/people/${person.id}`, body)
        : api.post("/api/people", body);
    },
    { invalidate: [["people"]], success: t("common.saved") },
  );
  return (
    <Modal opened onClose={onClose} title={person ? person.name : t("ppl.new")}>
      <Stack>
        <TextInput
          label={t("common.name")}
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
        />
        <Select
          label={t("ppl.kind")}
          data={[
            { value: "person", label: t("ppl.person") },
            { value: "pet", label: t("ppl.pet") },
          ]}
          value={kind}
          onChange={(v) => setKind(v ?? "person")}
        />
        {kind === "pet" && (
          <TextInput
            label={t("ppl.species")}
            value={species}
            onChange={(e) => setSpecies(e.currentTarget.value)}
          />
        )}
        <Textarea
          label={t("ppl.notes")}
          value={notes}
          onChange={(e) => setNotes(e.currentTarget.value)}
        />
        <Switch
          label={t("ppl.recognition")}
          checked={recognition}
          onChange={(e) => setRecognition(e.currentTarget.checked)}
        />
        <Button
          onClick={async () => {
            await save.mutateAsync(undefined);
            onClose();
          }}
          disabled={!name}
        >
          {t("common.save")}
        </Button>
      </Stack>
    </Modal>
  );
}

function EnrollModal({
  person,
  onClose,
}: {
  person: Person;
  onClose: () => void;
}) {
  const devices = useQuery({
    queryKey: ["devices"],
    queryFn: () => api.get<Device[]>("/api/devices"),
  });
  const t = useT();
  const cameras = (devices.data ?? []).filter(
    (d) => d.capabilities.includes("video.input") && d.status === "online",
  );
  const [camera, setCamera] = useState<string | null>(null);
  const [consent, setConsent] = useState(person.biometric_consent);
  const enroll = useAction(
    () =>
      api.post<{ added: number; rejected: number; reasons: string[] }>(
        `/api/people/${person.id}/enroll`,
        { device_id: camera, consent },
      ),
    {
      invalidate: [["people"], ["faces", person.id]],
      success: (r) =>
        t("ppl.enrolled", { added: r.added, rejected: r.rejected }),
    },
  );
  return (
    <Modal
      opened
      onClose={onClose}
      title={t("ppl.enrollTitle", { name: person.name })}
    >
      <Stack>
        <Alert color="blue">{t("ppl.enrollHint")}</Alert>
        <Select
          label={t("ppl.camera")}
          data={cameras.map((d) => ({ value: d.id, label: d.name }))}
          value={camera}
          onChange={setCamera}
        />
        <Checkbox
          label={t("ppl.consent", { name: person.name })}
          checked={consent}
          onChange={(e) => setConsent(e.currentTarget.checked)}
        />
        {enroll.data?.reasons.map((r) => (
          <Text key={r} size="xs" c="dimmed">
            {r}
          </Text>
        ))}
        <Button
          onClick={() => enroll.mutate(undefined)}
          loading={enroll.isPending}
          disabled={!camera || !consent}
        >
          {t("ppl.capture")}
        </Button>
      </Stack>
    </Modal>
  );
}

function Faces({ person }: { person: Person }) {
  const t = useT();
  const faces = useQuery({
    queryKey: ["faces", person.id],
    queryFn: () => api.get<Face[]>(`/api/people/${person.id}/faces`),
  });
  const del = useAction((id: string) => api.del(`/api/people/faces/${id}`), {
    invalidate: [["faces", person.id], ["people"]],
  });
  return (
    <Group gap="xs">
      {faces.data?.map((f) => (
        <Stack key={f.id} gap={2} align="center">
          {f.has_thumbnail ? (
            <Image
              src={`/api/people/faces/${f.id}/thumbnail.jpg`}
              w={56}
              h={56}
              radius="sm"
              alt={t("ppl.face")}
            />
          ) : (
            <IconFaceId size={40} />
          )}
          <ActionIcon
            size="xs"
            variant="subtle"
            color="red"
            onClick={() => del.mutate(f.id)}
          >
            <IconTrash size={12} />
          </ActionIcon>
        </Stack>
      ))}
    </Group>
  );
}

export function PeoplePage() {
  const people = useQuery({
    queryKey: ["people"],
    queryFn: () => api.get<Person[]>("/api/people"),
    refetchInterval: 10000,
  });
  const [editing, setEditing] = useState<Person | null | "new">(null);
  const t = useT();
  const [enrolling, setEnrolling] = useState<Person | null>(null);
  const [mergeFrom, setMergeFrom] = useState<Person | null>(null);
  const [mergeInto, setMergeInto] = useState<string | null>(null);
  const del = useAction((id: string) => api.del(`/api/people/${id}`), {
    invalidate: [["people"]],
    success: t("ppl.deleted"),
  });
  const revoke = useAction(
    (id: string) =>
      api.post(`/api/people/${id}/consent`, { kind: "face", granted: false }),
    {
      invalidate: [["people"]],
      success: t("ppl.consentRevoked"),
    },
  );
  const forgetVoice = useAction(
    (id: string) =>
      api.post(`/api/people/${id}/consent`, { kind: "voice", granted: false }),
    {
      invalidate: [["people"]],
      success: t("ppl.voiceDeleted"),
    },
  );
  const merge = useAction(
    () => api.post(`/api/people/${mergeFrom!.id}/merge`, { into: mergeInto }),
    { invalidate: [["people"]], success: t("ppl.merged") },
  );
  const exportPerson = async (p: Person) => {
    try {
      const data = await api.get(`/api/people/${p.id}/export`);
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
      );
      const a = document.createElement("a");
      a.href = url;
      a.download = `${p.name}-export.json`;
      a.click();
    } catch (err) {
      notifyError(err);
    }
  };

  return (
    <Stack>
      <PageHeader
        title={t("ppl.title")}
        description={t("ppl.desc")}
        actions={
          <Button
            leftSection={<IconPlus size={16} />}
            onClick={() => setEditing("new")}
          >
            {t("ppl.add")}
          </Button>
        }
      />
      <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }}>
        {people.data?.map((p) => (
          <Card key={p.id} withBorder>
            <Group justify="space-between">
              <Title order={5}>{p.name}</Title>
              <Group gap={4}>
                <Badge variant="light">
                  {p.kind === "pet"
                    ? (p.species ?? t("ppl.animal"))
                    : t("ppl.person")}
                </Badge>
                {p.biometric_consent ? (
                  <Badge color="green">{t("ppl.hasConsent")}</Badge>
                ) : (
                  <Badge color="gray">{t("ppl.noBiometrics")}</Badge>
                )}
                {!p.recognition_enabled && (
                  <Badge color="orange">{t("ppl.recognitionOff")}</Badge>
                )}
              </Group>
            </Group>
            <Text size="xs" c="dimmed">
              {t("ppl.faceCount", { n: p.face_count })} ·{" "}
              {p.voice_count
                ? t("ppl.voiceProfile", { n: p.voice_count })
                : t("ppl.noVoice")}
              {p.last_seen &&
                t("ppl.lastSeen", {
                  when: `${fmtTime(p.last_seen.at)}${p.last_seen.room ? ` (${p.last_seen.room})` : ""}`,
                })}
            </Text>
            {p.notes && <Text size="sm">{p.notes}</Text>}
            {p.face_count > 0 && <Faces person={p} />}
            <Group gap="xs" mt="sm">
              <Button size="xs" variant="light" onClick={() => setEditing(p)}>
                {t("common.edit")}
              </Button>
              {p.kind === "person" && (
                <Button
                  size="xs"
                  variant="light"
                  leftSection={<IconFaceId size={14} />}
                  onClick={() => setEnrolling(p)}
                >
                  {t("ppl.registerFace")}
                </Button>
              )}
              <Button
                size="xs"
                variant="subtle"
                leftSection={<IconDownload size={14} />}
                onClick={() => exportPerson(p)}
              >
                {t("ppl.export")}
              </Button>
              <Button
                size="xs"
                variant="subtle"
                onClick={() => setMergeFrom(p)}
              >
                {t("ppl.merge")}
              </Button>
              {p.biometric_consent && (
                <Button
                  size="xs"
                  variant="subtle"
                  color="orange"
                  onClick={() =>
                    confirm(t("ppl.confirmRevoke")) && revoke.mutate(p.id)
                  }
                >
                  {t("ppl.revoke")}
                </Button>
              )}
              {!!p.voice_count && (
                <Button
                  size="xs"
                  variant="subtle"
                  color="orange"
                  onClick={() =>
                    confirm(t("ppl.confirmVoiceDelete")) &&
                    forgetVoice.mutate(p.id)
                  }
                >
                  {t("ppl.deleteVoice")}
                </Button>
              )}
              <Button
                size="xs"
                variant="subtle"
                color="red"
                onClick={() =>
                  confirm(t("ppl.confirmDelete", { name: p.name })) &&
                  del.mutate(p.id)
                }
              >
                {t("common.delete")}
              </Button>
            </Group>
          </Card>
        ))}
      </SimpleGrid>
      {editing && (
        <PersonModal
          person={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
        />
      )}
      {enrolling && (
        <EnrollModal person={enrolling} onClose={() => setEnrolling(null)} />
      )}
      {mergeFrom && (
        <Modal
          opened
          onClose={() => setMergeFrom(null)}
          title={t("ppl.mergeTitle", { name: mergeFrom.name })}
        >
          <Stack>
            <Select
              data={(people.data ?? [])
                .filter((p) => p.id !== mergeFrom.id)
                .map((p) => ({ value: p.id, label: p.name }))}
              value={mergeInto}
              onChange={setMergeInto}
            />
            <Text size="xs" c="dimmed">
              {t("ppl.mergeHint", { name: mergeFrom.name })}
            </Text>
            <Button
              disabled={!mergeInto}
              onClick={async () => {
                await merge.mutateAsync(undefined);
                setMergeFrom(null);
              }}
            >
              {t("ppl.merge")}
            </Button>
          </Stack>
        </Modal>
      )}
    </Stack>
  );
}
