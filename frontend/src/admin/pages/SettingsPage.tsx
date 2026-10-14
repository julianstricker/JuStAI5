import { Badge, Button, Card, Group, Modal, NumberInput, PasswordInput, Select, SimpleGrid, Stack, Switch, Table, Text, TextInput, Title } from "@mantine/core";
import { IconPlus } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "@/shared/api";

import { useIsAdmin, useMe } from "../auth";
import { PageHeader, fmtTime, useAction } from "../components/common";

interface UserRow {
  id: string;
  username: string;
  display_name: string;
  role: string;
  disabled: boolean;
  person_id: string | null;
  last_login_at: string | null;
}

interface SystemSettings {
  timezone: string;
  discovery_cidrs: string[];
  retention: { events_days: number; transcripts_days: number; sightings_days: number; snapshots_days: number };
  store_face_thumbnails: boolean;
  vision_snapshots: boolean;
}

function UserModal({ user, onClose }: { user: UserRow | null; onClose: () => void }) {
  const people = useQuery({ queryKey: ["people"], queryFn: () => api.get<{ id: string; name: string }[]>("/api/people") });
  const [username, setUsername] = useState(user?.username ?? "");
  const [displayName, setDisplayName] = useState(user?.display_name ?? "");
  const [role, setRole] = useState(user?.role ?? "resident");
  const [password, setPassword] = useState("");
  const [person, setPerson] = useState<string | null>(user?.person_id ?? null);
  const save = useAction(
    () =>
      user
        ? api.patch(`/api/auth/users/${user.id}`, { role, display_name: displayName, password: password || undefined, person_id: person ?? "" })
        : api.post("/api/auth/users", { username, password, role, display_name: displayName, person_id: person }),
    { invalidate: [["users"]], success: "Benutzer gespeichert" },
  );
  return (
    <Modal opened onClose={onClose} title={user ? `Benutzer ${user.username}` : "Neuer Benutzer"}>
      <Stack>
        {!user && <TextInput label="Benutzername" value={username} onChange={(e) => setUsername(e.currentTarget.value)} />}
        <TextInput label="Anzeigename" value={displayName} onChange={(e) => setDisplayName(e.currentTarget.value)} />
        <Select
          label="Rolle"
          data={[
            { value: "admin", label: "Administrator" },
            { value: "resident", label: "Bewohner" },
            { value: "guest", label: "Gast" },
          ]}
          value={role}
          onChange={(v) => setRole(v ?? "resident")}
        />
        <Select label="Verknüpfte Person" clearable data={(people.data ?? []).map((p) => ({ value: p.id, label: p.name }))} value={person} onChange={setPerson} />
        <PasswordInput label={user ? "Neues Passwort (optional)" : "Passwort"} value={password} onChange={(e) => setPassword(e.currentTarget.value)} />
        <Button
          onClick={async () => {
            await save.mutateAsync(undefined);
            onClose();
          }}
        >
          Speichern
        </Button>
      </Stack>
    </Modal>
  );
}

export function SettingsPage() {
  const isAdmin = useIsAdmin();
  const me = useMe();
  const users = useQuery({ queryKey: ["users"], queryFn: () => api.get<UserRow[]>("/api/auth/users"), enabled: isAdmin });
  const settings = useQuery({ queryKey: ["system-settings"], queryFn: () => api.get<SystemSettings>("/api/settings/system") });
  const [draft, setDraft] = useState<SystemSettings | null>(null);
  const [editing, setEditing] = useState<UserRow | null | "new">(null);
  useEffect(() => {
    if (settings.data) setDraft(settings.data);
  }, [settings.data]);
  const saveSettings = useAction((s: SystemSettings) => api.put("/api/settings/system", s), { invalidate: [["system-settings"]], success: "Einstellungen gespeichert" });
  const toggleUser = useAction((u: UserRow) => api.patch(`/api/auth/users/${u.id}`, { disabled: !u.disabled }), { invalidate: [["users"]] });
  const logoutAll = useAction(() => api.post("/api/auth/logout-all"), { success: "Alle Sitzungen beendet" });

  return (
    <Stack>
      <PageHeader title="Einstellungen" description="Benutzer, Aufbewahrung, Netzwerksuche und Datensicherung" />
      {draft && isAdmin && (
        <SimpleGrid cols={{ base: 1, lg: 2 }}>
          <Card withBorder>
            <Stack>
              <Title order={5}>System</Title>
              <TextInput label="Zeitzone" value={draft.timezone} onChange={(e) => setDraft({ ...draft, timezone: e.currentTarget.value })} />
              <TextInput
                label="Autorisierte Netzbereiche für die Gerätesuche"
                description="Kommagetrennte CIDR-Bereiche, z. B. 192.168.0.0/24"
                value={draft.discovery_cidrs.join(", ")}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    discovery_cidrs: e.currentTarget.value
                      .split(",")
                      .map((s) => s.trim())
                      .filter(Boolean),
                  })
                }
              />
              <Switch
                label="Gesichts-Vorschaubilder speichern"
                description="Kleine Ausschnitte zur Kontrolle von Gesichtsprofilen"
                checked={draft.store_face_thumbnails}
                onChange={(e) => setDraft({ ...draft, store_face_thumbnails: e.currentTarget.checked })}
              />
              <Switch
                label="Snapshots zu Sichtungen speichern"
                checked={draft.vision_snapshots}
                onChange={(e) => setDraft({ ...draft, vision_snapshots: e.currentTarget.checked })}
              />
            </Stack>
          </Card>
          <Card withBorder>
            <Stack>
              <Title order={5}>Aufbewahrung (Tage)</Title>
              {(
                [
                  ["events_days", "Persistente Ereignisse"],
                  ["transcripts_days", "Gesprächstranskripte"],
                  ["sightings_days", "Sichtungen"],
                  ["snapshots_days", "Snapshots"],
                ] as const
              ).map(([k, label]) => (
                <NumberInput
                  key={k}
                  label={label}
                  min={1}
                  value={draft.retention[k]}
                  onChange={(v) => setDraft({ ...draft, retention: { ...draft.retention, [k]: Number(v) } })}
                />
              ))}
              <Button onClick={() => saveSettings.mutate(draft)} loading={saveSettings.isPending}>
                Speichern
              </Button>
            </Stack>
          </Card>
        </SimpleGrid>
      )}
      {isAdmin && (
        <Card withBorder>
          <Group justify="space-between" mb="sm">
            <Title order={5}>Benutzer</Title>
            <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => setEditing("new")}>
              Benutzer
            </Button>
          </Group>
          <Table>
            <Table.Tbody>
              {users.data?.map((u) => (
                <Table.Tr key={u.id}>
                  <Table.Td>{u.username}</Table.Td>
                  <Table.Td>{u.display_name}</Table.Td>
                  <Table.Td>
                    <Badge>{u.role}</Badge>
                  </Table.Td>
                  <Table.Td>{fmtTime(u.last_login_at)}</Table.Td>
                  <Table.Td>
                    <Group gap="xs">
                      <Button size="compact-xs" variant="subtle" onClick={() => setEditing(u)}>
                        Bearbeiten
                      </Button>
                      {u.id !== me.id && (
                        <Button size="compact-xs" variant="subtle" color={u.disabled ? "green" : "red"} onClick={() => toggleUser.mutate(u)}>
                          {u.disabled ? "Aktivieren" : "Sperren"}
                        </Button>
                      )}
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Card>
      )}
      <Card withBorder>
        <Stack>
          <Title order={5}>Sicherheit & Datensicherung</Title>
          <Button variant="light" w={260} onClick={() => logoutAll.mutate(undefined)}>
            Alle meine Sitzungen abmelden
          </Button>
          <Text size="sm">
            Vollständige Sicherung (Datenbank, Konfiguration, Plugins, Schlüssel): <code>./scripts/backup.sh</code>. Wiederherstellung:{" "}
            <code>./scripts/restore.sh &lt;backup.tar.gz&gt;</code>. Details in docs/DEPLOYMENT.md.
          </Text>
        </Stack>
      </Card>
      {editing && <UserModal user={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </Stack>
  );
}
