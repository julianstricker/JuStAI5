import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  FileButton,
  Group,
  Modal,
  SimpleGrid,
  Stack,
  Switch,
  Text,
  Title,
} from "@mantine/core";
import { IconSettings, IconTrash, IconUpload } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/shared/api";
import type { PluginInfo } from "@/shared/types";

import { type Key, useT } from "@/shared/i18n";

import { JsonSchemaForm } from "../components/JsonSchemaForm";
import { PageHeader, StatusBadge, useAction } from "../components/common";

const PERMISSION_HINTS: Record<string, Key> = {
  "camera.read": "perm.camera.read",
  "camera.ptz": "perm.camera.ptz",
  "speaker.write": "perm.speaker.write",
  "display.write": "perm.display.write",
  "memory.read": "perm.memory.read",
  "memory.write": "perm.memory.write",
  "network.http": "perm.network.http",
  "network.lan": "perm.network.lan",
  "ai.provide": "perm.ai.provide",
  "devices.provide": "perm.devices.provide",
  "tools.provide": "perm.tools.provide",
  "storage.plugin": "perm.storage.plugin",
  "events.publish": "perm.events.publish",
  "events.subscribe": "perm.events.subscribe",
  "automation.manage": "perm.automation.manage",
};

function ConfigModal({
  plugin,
  onClose,
}: {
  plugin: PluginInfo;
  onClose: () => void;
}) {
  const [config, setConfig] = useState<Record<string, unknown>>(
    Object.fromEntries(
      Object.entries(plugin.config).filter(
        ([k]) => !plugin.manifest.secret_fields.includes(k),
      ),
    ),
  );
  const [granted, setGranted] = useState<string[]>(plugin.granted_permissions);
  const t = useT();
  const save = useAction(
    () =>
      api.put(`/api/plugins/${plugin.id}/config`, {
        config,
        granted_permissions: granted,
      }),
    {
      invalidate: [["plugins"]],
      success: t("plug.configSaved"),
    },
  );
  return (
    <Modal opened onClose={onClose} title={plugin.manifest.name} size="lg">
      <Stack>
        <Text size="sm">{plugin.manifest.description}</Text>
        <Title order={6}>{t("plug.permissions")}</Title>
        {plugin.manifest.permissions.map((p) => (
          <Checkbox
            key={p}
            label={`${p} – ${PERMISSION_HINTS[p] ? t(PERMISSION_HINTS[p]) : ""}`}
            checked={granted.includes(p)}
            onChange={(e) =>
              setGranted(
                e.currentTarget.checked
                  ? [...granted, p]
                  : granted.filter((g) => g !== p),
              )
            }
          />
        ))}
        {!!plugin.manifest.network_allowlist.length && (
          <Text size="xs" c="dimmed">
            {t("plug.allowedHosts", {
              hosts: plugin.manifest.network_allowlist.join(", "),
            })}
          </Text>
        )}
        <Title order={6}>{t("plug.configuration")}</Title>
        <JsonSchemaForm
          schema={plugin.manifest.config_schema}
          value={config}
          onChange={setConfig}
          secretFields={plugin.manifest.secret_fields}
        />
        <Button
          onClick={async () => {
            await save.mutateAsync(undefined);
            onClose();
          }}
          loading={save.isPending}
        >
          {t("plug.saveRestart")}
        </Button>
      </Stack>
    </Modal>
  );
}

export function PluginsPage() {
  const plugins = useQuery({
    queryKey: ["plugins"],
    queryFn: () => api.get<PluginInfo[]>("/api/plugins"),
    refetchInterval: 5000,
  });
  const [configuring, setConfiguring] = useState<PluginInfo | null>(null);
  const t = useT();
  const toggle = useAction(
    ({ id, enable }: { id: string; enable: boolean }) =>
      api.post(`/api/plugins/${id}/${enable ? "enable" : "disable"}`),
    {
      invalidate: [["plugins"]],
    },
  );
  const remove = useAction((id: string) => api.del(`/api/plugins/${id}`), {
    invalidate: [["plugins"]],
    success: t("plug.removed"),
  });
  const upload = useAction(
    (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return api.upload<{ id: string; version: string }>(
        "/api/plugins/install",
        form,
      );
    },
    {
      invalidate: [["plugins"]],
      success: (r) => t("plug.installed", { id: r.id, version: r.version }),
    },
  );

  return (
    <Stack>
      <PageHeader
        title={t("nav.plugins")}
        description={t("plug.desc")}
        actions={
          <FileButton onChange={(f) => f && upload.mutate(f)} accept=".zip">
            {(props) => (
              <Button
                {...props}
                leftSection={<IconUpload size={16} />}
                loading={upload.isPending}
              >
                {t("plug.install")}
              </Button>
            )}
          </FileButton>
        }
      />
      <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }}>
        {plugins.data?.map((p) => (
          <Card key={p.id} withBorder>
            <Group justify="space-between">
              <Stack gap={0}>
                <Text fw={600}>{p.manifest.name}</Text>
                <Text size="xs" c="dimmed">
                  {p.id} {p.version} · {p.source} · {p.manifest.trust}
                </Text>
              </Stack>
              <Switch
                checked={p.enabled}
                onChange={(e) =>
                  toggle.mutate({ id: p.id, enable: e.currentTarget.checked })
                }
              />
            </Group>
            <Text size="sm" mt="xs" lineClamp={3}>
              {p.manifest.description}
            </Text>
            <Group gap={4} mt="xs">
              <StatusBadge status={p.status} />
              {p.health && p.health.state !== "ok" && (
                <Badge color="orange">
                  {p.health.detail ?? p.health.state}
                </Badge>
              )}
              {p.manifest.types.map((type) => (
                <Badge key={type} size="xs" variant="outline">
                  {type}
                </Badge>
              ))}
            </Group>
            {p.error && (
              <Alert color="red" mt="xs" p="xs">
                <Text size="xs">{p.error}</Text>
              </Alert>
            )}
            {p.running &&
              (p.provides.providers.length > 0 ||
                p.provides.tools.length > 0) && (
                <Text size="xs" c="dimmed" mt="xs">
                  {t("plug.provides", {
                    list: [...p.provides.providers, ...p.provides.tools].join(
                      ", ",
                    ),
                  })}
                </Text>
              )}
            <Group mt="sm" gap="xs">
              <Button
                size="xs"
                variant="light"
                leftSection={<IconSettings size={14} />}
                onClick={() => setConfiguring(p)}
              >
                {t("plug.configure")}
              </Button>
              {p.source !== "builtin" && (
                <Button
                  size="xs"
                  color="red"
                  variant="subtle"
                  leftSection={<IconTrash size={14} />}
                  onClick={() =>
                    confirm(t("plug.confirmRemove", { id: p.id })) &&
                    remove.mutate(p.id)
                  }
                >
                  {t("common.remove")}
                </Button>
              )}
            </Group>
          </Card>
        ))}
      </SimpleGrid>
      {configuring && (
        <ConfigModal
          plugin={configuring}
          onClose={() => setConfiguring(null)}
        />
      )}
    </Stack>
  );
}
