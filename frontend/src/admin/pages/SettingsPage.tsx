import {
  Badge,
  Button,
  Card,
  Group,
  Modal,
  NumberInput,
  PasswordInput,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { IconPlus } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { rich, useT } from "@/shared/i18n";

import { api } from "@/shared/api";

import { useIsAdmin, useMe } from "../auth";
import { PageHeader, fmtTime, useAction } from "../components/common";
import { DeviceAppCard } from "../components/DeviceAppCard";

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
  retention: {
    events_days: number;
    transcripts_days: number;
    sightings_days: number;
    tool_executions_days: number;
  };
  store_face_thumbnails: boolean;
}

function UserModal({
  user,
  onClose,
}: {
  user: UserRow | null;
  onClose: () => void;
}) {
  const people = useQuery({
    queryKey: ["people"],
    queryFn: () => api.get<{ id: string; name: string }[]>("/api/people"),
  });
  const [username, setUsername] = useState(user?.username ?? "");
  const [displayName, setDisplayName] = useState(user?.display_name ?? "");
  const [role, setRole] = useState(user?.role ?? "resident");
  const [password, setPassword] = useState("");
  const [person, setPerson] = useState<string | null>(user?.person_id ?? null);
  const t = useT();
  const save = useAction(
    () =>
      user
        ? api.patch(`/api/auth/users/${user.id}`, {
            role,
            display_name: displayName,
            password: password || undefined,
            person_id: person ?? "",
          })
        : api.post("/api/auth/users", {
            username,
            password,
            role,
            display_name: displayName,
            person_id: person,
          }),
    { invalidate: [["users"]], success: t("set.userSaved") },
  );
  return (
    <Modal
      opened
      onClose={onClose}
      title={
        user ? t("set.userTitle", { name: user.username }) : t("set.newUser")
      }
    >
      <Stack>
        {!user && (
          <TextInput
            label={t("set.username")}
            value={username}
            onChange={(e) => setUsername(e.currentTarget.value)}
          />
        )}
        <TextInput
          label={t("set.displayName")}
          value={displayName}
          onChange={(e) => setDisplayName(e.currentTarget.value)}
        />
        <Select
          label={t("set.role")}
          data={[
            { value: "admin", label: t("role.admin") },
            { value: "resident", label: t("role.resident") },
            { value: "guest", label: t("role.guest") },
          ]}
          value={role}
          onChange={(v) => setRole(v ?? "resident")}
        />
        <Select
          label={t("set.linkedPerson")}
          clearable
          data={(people.data ?? []).map((p) => ({
            value: p.id,
            label: p.name,
          }))}
          value={person}
          onChange={setPerson}
        />
        <PasswordInput
          label={user ? t("set.newPassword") : t("login.password")}
          value={password}
          onChange={(e) => setPassword(e.currentTarget.value)}
        />
        <Button
          onClick={async () => {
            await save.mutateAsync(undefined);
            onClose();
          }}
        >
          {t("common.save")}
        </Button>
      </Stack>
    </Modal>
  );
}

export function SettingsPage() {
  const isAdmin = useIsAdmin();
  const me = useMe();
  const users = useQuery({
    queryKey: ["users"],
    queryFn: () => api.get<UserRow[]>("/api/auth/users"),
    enabled: isAdmin,
  });
  const settings = useQuery({
    queryKey: ["system-settings"],
    queryFn: () => api.get<SystemSettings>("/api/settings/system"),
  });
  const [draft, setDraft] = useState<SystemSettings | null>(null);
  const [editing, setEditing] = useState<UserRow | null | "new">(null);
  const t = useT();
  useEffect(() => {
    if (settings.data) setDraft(settings.data);
  }, [settings.data]);
  const saveSettings = useAction(
    (s: SystemSettings) => api.put("/api/settings/system", s),
    { invalidate: [["system-settings"]], success: t("set.saved") },
  );
  const toggleUser = useAction(
    (u: UserRow) =>
      api.patch(`/api/auth/users/${u.id}`, { disabled: !u.disabled }),
    { invalidate: [["users"]] },
  );
  const logoutAll = useAction(() => api.post("/api/auth/logout-all"), {
    success: t("set.loggedOutAll"),
  });

  return (
    <Stack>
      <PageHeader title={t("nav.settings")} description={t("set.desc")} />
      {isAdmin && <DeviceAppCard />}
      {draft && isAdmin && (
        <SimpleGrid cols={{ base: 1, lg: 2 }}>
          <Card withBorder>
            <Stack>
              <Title order={5}>{t("set.system")}</Title>
              <TextInput
                label={t("set.timezone")}
                description={t("set.timezoneHint")}
                value={draft.timezone}
                onChange={(e) =>
                  setDraft({ ...draft, timezone: e.currentTarget.value })
                }
              />
              <TextInput
                label={t("set.cidrs")}
                description={t("set.cidrsHint")}
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
                label={t("set.thumbs")}
                description={t("set.thumbsHint")}
                checked={draft.store_face_thumbnails}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    store_face_thumbnails: e.currentTarget.checked,
                  })
                }
              />
            </Stack>
          </Card>
          <Card withBorder>
            <Stack>
              <Title order={5}>{t("set.retention")}</Title>
              {(
                [
                  ["events_days", "set.retEvents"],
                  ["transcripts_days", "set.retTranscripts"],
                  ["sightings_days", "set.retSightings"],
                  ["tool_executions_days", "set.retTools"],
                ] as const
              ).map(([k, label]) => (
                <NumberInput
                  key={k}
                  label={t(label)}
                  min={1}
                  value={draft.retention[k]}
                  onChange={(v) =>
                    setDraft({
                      ...draft,
                      retention: { ...draft.retention, [k]: Number(v) },
                    })
                  }
                />
              ))}
              <Button
                onClick={() => saveSettings.mutate(draft)}
                loading={saveSettings.isPending}
              >
                {t("common.save")}
              </Button>
            </Stack>
          </Card>
        </SimpleGrid>
      )}
      {isAdmin && (
        <Card withBorder>
          <Group justify="space-between" mb="sm">
            <Title order={5}>{t("set.users")}</Title>
            <Button
              size="xs"
              leftSection={<IconPlus size={14} />}
              onClick={() => setEditing("new")}
            >
              {t("set.addUser")}
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
                      <Button
                        size="compact-xs"
                        variant="subtle"
                        onClick={() => setEditing(u)}
                      >
                        {t("common.edit")}
                      </Button>
                      {u.id !== me.id && (
                        <Button
                          size="compact-xs"
                          variant="subtle"
                          color={u.disabled ? "green" : "red"}
                          onClick={() => toggleUser.mutate(u)}
                        >
                          {u.disabled ? t("set.enable") : t("set.lock")}
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
          <Title order={5}>{t("set.security")}</Title>
          <Button
            variant="light"
            w={260}
            onClick={() => logoutAll.mutate(undefined)}
          >
            {t("set.logoutAll")}
          </Button>
          <Text size="sm">
            {rich(t("set.backupHint"), {
              backup: <code>./scripts/backup.sh</code>,
              restore: <code>./scripts/restore.sh &lt;backup.tar.gz&gt;</code>,
            })}
          </Text>
        </Stack>
      </Card>
      {editing && (
        <UserModal
          user={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
        />
      )}
    </Stack>
  );
}
