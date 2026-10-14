import { ActionIcon, Alert, Badge, Button, Card, Checkbox, Group, Image, Modal, Select, SimpleGrid, Stack, Switch, Text, TextInput, Textarea, Title } from "@mantine/core";
import { IconDownload, IconFaceId, IconPlus, IconTrash } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/shared/api";
import type { Device } from "@/shared/types";

import { PageHeader, fmtTime, notifyError, useAction } from "../components/common";

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
  last_seen: { at: string; camera: string | null; room: string | null } | null;
}

interface Face {
  id: string;
  quality: Record<string, number>;
  source: string;
  created_at: string;
  has_thumbnail: boolean;
}

function PersonModal({ person, onClose }: { person: Person | null; onClose: () => void }) {
  const [name, setName] = useState(person?.name ?? "");
  const [kind, setKind] = useState<string>(person?.kind ?? "person");
  const [species, setSpecies] = useState(person?.species ?? "");
  const [notes, setNotes] = useState(person?.notes ?? "");
  const [recognition, setRecognition] = useState(person?.recognition_enabled ?? true);
  const save = useAction(
    () => {
      const body = { name, kind, species: species || null, notes, recognition_enabled: recognition };
      return person ? api.patch(`/api/people/${person.id}`, body) : api.post("/api/people", body);
    },
    { invalidate: [["people"]], success: "Gespeichert" },
  );
  return (
    <Modal opened onClose={onClose} title={person ? person.name : "Neue Person / neues Tier"}>
      <Stack>
        <TextInput label="Name" value={name} onChange={(e) => setName(e.currentTarget.value)} />
        <Select
          label="Art"
          data={[
            { value: "person", label: "Person" },
            { value: "pet", label: "Haustier" },
          ]}
          value={kind}
          onChange={(v) => setKind(v ?? "person")}
        />
        {kind === "pet" && <TextInput label="Tierart (z. B. dog, cat)" value={species} onChange={(e) => setSpecies(e.currentTarget.value)} />}
        <Textarea label="Notizen" value={notes} onChange={(e) => setNotes(e.currentTarget.value)} />
        <Switch label="Wiedererkennung aktiv" checked={recognition} onChange={(e) => setRecognition(e.currentTarget.checked)} />
        <Button
          onClick={async () => {
            await save.mutateAsync(undefined);
            onClose();
          }}
          disabled={!name}
        >
          Speichern
        </Button>
      </Stack>
    </Modal>
  );
}

function EnrollModal({ person, onClose }: { person: Person; onClose: () => void }) {
  const devices = useQuery({ queryKey: ["devices"], queryFn: () => api.get<Device[]>("/api/devices") });
  const cameras = (devices.data ?? []).filter((d) => d.capabilities.includes("video.input") && d.status === "online");
  const [camera, setCamera] = useState<string | null>(null);
  const [consent, setConsent] = useState(person.biometric_consent);
  const enroll = useAction(
    () => api.post<{ added: number; rejected: number; reasons: string[] }>(`/api/people/${person.id}/enroll`, { device_id: camera, consent }),
    { invalidate: [["people"], ["faces", person.id]], success: (r) => `${r.added} Aufnahmen gespeichert, ${r.rejected} verworfen` },
  );
  return (
    <Modal opened onClose={onClose} title={`Gesicht registrieren: ${person.name}`}>
      <Stack>
        <Alert color="blue">
          Die Person sollte allein und frontal vor der Kamera stehen. Es werden über einige Sekunden mehrere Aufnahmen gemacht; nur ausreichend scharfe,
          große und helle Gesichter werden gespeichert.
        </Alert>
        <Select label="Kamera" data={cameras.map((d) => ({ value: d.id, label: d.name }))} value={camera} onChange={setCamera} />
        <Checkbox
          label={`${person.name} hat der Speicherung biometrischer Merkmale zur Wiedererkennung ausdrücklich zugestimmt.`}
          checked={consent}
          onChange={(e) => setConsent(e.currentTarget.checked)}
        />
        {enroll.data?.reasons.map((r) => (
          <Text key={r} size="xs" c="dimmed">
            {r}
          </Text>
        ))}
        <Button onClick={() => enroll.mutate(undefined)} loading={enroll.isPending} disabled={!camera || !consent}>
          Aufnehmen
        </Button>
      </Stack>
    </Modal>
  );
}

function Faces({ person }: { person: Person }) {
  const faces = useQuery({ queryKey: ["faces", person.id], queryFn: () => api.get<Face[]>(`/api/people/${person.id}/faces`) });
  const del = useAction((id: string) => api.del(`/api/people/faces/${id}`), { invalidate: [["faces", person.id], ["people"]] });
  return (
    <Group gap="xs">
      {faces.data?.map((f) => (
        <Stack key={f.id} gap={2} align="center">
          {f.has_thumbnail ? (
            <Image src={`/api/people/faces/${f.id}/thumbnail.jpg`} w={56} h={56} radius="sm" alt="Gesicht" />
          ) : (
            <IconFaceId size={40} />
          )}
          <ActionIcon size="xs" variant="subtle" color="red" onClick={() => del.mutate(f.id)}>
            <IconTrash size={12} />
          </ActionIcon>
        </Stack>
      ))}
    </Group>
  );
}

export function PeoplePage() {
  const people = useQuery({ queryKey: ["people"], queryFn: () => api.get<Person[]>("/api/people"), refetchInterval: 10000 });
  const [editing, setEditing] = useState<Person | null | "new">(null);
  const [enrolling, setEnrolling] = useState<Person | null>(null);
  const [mergeFrom, setMergeFrom] = useState<Person | null>(null);
  const [mergeInto, setMergeInto] = useState<string | null>(null);
  const del = useAction((id: string) => api.del(`/api/people/${id}`), { invalidate: [["people"]], success: "Person und alle biometrischen Daten gelöscht" });
  const revoke = useAction((id: string) => api.post(`/api/people/${id}/consent`, { kind: "face", granted: false }), {
    invalidate: [["people"]],
    success: "Einwilligung widerrufen, Gesichtsdaten gelöscht",
  });
  const merge = useAction(() => api.post(`/api/people/${mergeFrom!.id}/merge`, { into: mergeInto }), { invalidate: [["people"]], success: "Profile zusammengeführt" });
  const exportPerson = async (p: Person) => {
    try {
      const data = await api.get(`/api/people/${p.id}/export`);
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
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
        title="Personen & Haustiere"
        description="Bekannte Personen, Gesichtsprofile und Einwilligungen. Biometrische Merkmale gewähren niemals Admin-Rechte."
        actions={
          <Button leftSection={<IconPlus size={16} />} onClick={() => setEditing("new")}>
            Person
          </Button>
        }
      />
      <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }}>
        {people.data?.map((p) => (
          <Card key={p.id} withBorder>
            <Group justify="space-between">
              <Title order={5}>{p.name}</Title>
              <Group gap={4}>
                <Badge variant="light">{p.kind === "pet" ? (p.species ?? "Tier") : "Person"}</Badge>
                {p.biometric_consent ? <Badge color="green">Einwilligung</Badge> : <Badge color="gray">keine Biometrie</Badge>}
                {!p.recognition_enabled && <Badge color="orange">Erkennung aus</Badge>}
              </Group>
            </Group>
            <Text size="xs" c="dimmed">
              {p.face_count} Gesichtsaufnahmen
              {p.last_seen && ` · zuletzt gesehen ${fmtTime(p.last_seen.at)}${p.last_seen.room ? ` (${p.last_seen.room})` : ""}`}
            </Text>
            {p.notes && <Text size="sm">{p.notes}</Text>}
            {p.face_count > 0 && <Faces person={p} />}
            <Group gap="xs" mt="sm">
              <Button size="xs" variant="light" onClick={() => setEditing(p)}>
                Bearbeiten
              </Button>
              {p.kind === "person" && (
                <Button size="xs" variant="light" leftSection={<IconFaceId size={14} />} onClick={() => setEnrolling(p)}>
                  Gesicht registrieren
                </Button>
              )}
              <Button size="xs" variant="subtle" leftSection={<IconDownload size={14} />} onClick={() => exportPerson(p)}>
                Export
              </Button>
              <Button size="xs" variant="subtle" onClick={() => setMergeFrom(p)}>
                Zusammenführen
              </Button>
              {p.biometric_consent && (
                <Button size="xs" variant="subtle" color="orange" onClick={() => confirm("Einwilligung widerrufen und Gesichtsdaten löschen?") && revoke.mutate(p.id)}>
                  Einwilligung widerrufen
                </Button>
              )}
              <Button size="xs" variant="subtle" color="red" onClick={() => confirm(`${p.name} mit allen Daten löschen?`) && del.mutate(p.id)}>
                Löschen
              </Button>
            </Group>
          </Card>
        ))}
      </SimpleGrid>
      {editing && <PersonModal person={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
      {enrolling && <EnrollModal person={enrolling} onClose={() => setEnrolling(null)} />}
      {mergeFrom && (
        <Modal opened onClose={() => setMergeFrom(null)} title={`${mergeFrom.name} zusammenführen mit …`}>
          <Stack>
            <Select
              data={(people.data ?? []).filter((p) => p.id !== mergeFrom.id).map((p) => ({ value: p.id, label: p.name }))}
              value={mergeInto}
              onChange={setMergeInto}
            />
            <Text size="xs" c="dimmed">
              Gesichtsprofile, Erinnerungen und Automationen werden übertragen; das Profil „{mergeFrom.name}“ wird entfernt.
            </Text>
            <Button
              disabled={!mergeInto}
              onClick={async () => {
                await merge.mutateAsync(undefined);
                setMergeFrom(null);
              }}
            >
              Zusammenführen
            </Button>
          </Stack>
        </Modal>
      )}
    </Stack>
  );
}
