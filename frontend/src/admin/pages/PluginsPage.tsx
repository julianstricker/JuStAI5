import { Alert, Badge, Button, Card, Checkbox, FileButton, Group, Modal, SimpleGrid, Stack, Switch, Text, Title } from "@mantine/core";
import { IconSettings, IconTrash, IconUpload } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/shared/api";
import type { PluginInfo } from "@/shared/types";

import { JsonSchemaForm } from "../components/JsonSchemaForm";
import { PageHeader, StatusBadge, useAction } from "../components/common";

const PERMISSION_HINTS: Record<string, string> = {
  "camera.read": "Kamerabilder lesen",
  "camera.ptz": "Kameras bewegen",
  "speaker.write": "Über Lautsprecher sprechen",
  "display.write": "Auf Bildschirmen anzeigen",
  "memory.read": "Erinnerungen lesen",
  "memory.write": "Erinnerungen ändern",
  "network.http": "Internetzugriff (nur erlaubte Hosts)",
  "network.lan": "Zugriff auf Geräte im lokalen Netz",
  "ai.provide": "KI-Provider bereitstellen",
  "devices.provide": "Gerätetreiber bereitstellen",
  "tools.provide": "Werkzeuge für den Assistenten",
  "storage.plugin": "Eigener Datenspeicher",
  "events.publish": "Ereignisse senden",
  "events.subscribe": "Ereignisse empfangen",
  "automation.manage": "Automationen verwalten",
};

function ConfigModal({ plugin, onClose }: { plugin: PluginInfo; onClose: () => void }) {
  const [config, setConfig] = useState<Record<string, unknown>>(
    Object.fromEntries(Object.entries(plugin.config).filter(([k]) => !plugin.manifest.secret_fields.includes(k))),
  );
  const [granted, setGranted] = useState<string[]>(plugin.granted_permissions);
  const save = useAction(() => api.put(`/api/plugins/${plugin.id}/config`, { config, granted_permissions: granted }), {
    invalidate: [["plugins"]],
    success: "Plugin-Konfiguration gespeichert",
  });
  return (
    <Modal opened onClose={onClose} title={plugin.manifest.name} size="lg">
      <Stack>
        <Text size="sm">{plugin.manifest.description}</Text>
        <Title order={6}>Berechtigungen</Title>
        {plugin.manifest.permissions.map((p) => (
          <Checkbox
            key={p}
            label={`${p} – ${PERMISSION_HINTS[p] ?? ""}`}
            checked={granted.includes(p)}
            onChange={(e) => setGranted(e.currentTarget.checked ? [...granted, p] : granted.filter((g) => g !== p))}
          />
        ))}
        {!!plugin.manifest.network_allowlist.length && (
          <Text size="xs" c="dimmed">
            Erlaubte Hosts: {plugin.manifest.network_allowlist.join(", ")}
          </Text>
        )}
        <Title order={6}>Konfiguration</Title>
        <JsonSchemaForm schema={plugin.manifest.config_schema} value={config} onChange={setConfig} secretFields={plugin.manifest.secret_fields} />
        <Button
          onClick={async () => {
            await save.mutateAsync(undefined);
            onClose();
          }}
          loading={save.isPending}
        >
          Speichern (Plugin wird neu gestartet)
        </Button>
      </Stack>
    </Modal>
  );
}

export function PluginsPage() {
  const plugins = useQuery({ queryKey: ["plugins"], queryFn: () => api.get<PluginInfo[]>("/api/plugins"), refetchInterval: 5000 });
  const [configuring, setConfiguring] = useState<PluginInfo | null>(null);
  const toggle = useAction(({ id, enable }: { id: string; enable: boolean }) => api.post(`/api/plugins/${id}/${enable ? "enable" : "disable"}`), {
    invalidate: [["plugins"]],
  });
  const remove = useAction((id: string) => api.del(`/api/plugins/${id}`), { invalidate: [["plugins"]], success: "Plugin entfernt" });
  const upload = useAction(
    (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return api.upload<{ id: string; version: string }>("/api/plugins/install", form);
    },
    { invalidate: [["plugins"]], success: (r) => `Plugin ${r.id} ${r.version} installiert (noch nicht aktiviert)` },
  );

  return (
    <Stack>
      <PageHeader
        title="Plugins"
        description="Erweiterungen für Geräte, KI-Provider, Werkzeuge und Displays. Hochgeladene Plugins laufen isoliert in der Sandbox."
        actions={
          <FileButton onChange={(f) => f && upload.mutate(f)} accept=".zip">
            {(props) => (
              <Button {...props} leftSection={<IconUpload size={16} />} loading={upload.isPending}>
                Plugin installieren (.zip)
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
              <Switch checked={p.enabled} onChange={(e) => toggle.mutate({ id: p.id, enable: e.currentTarget.checked })} />
            </Group>
            <Text size="sm" mt="xs" lineClamp={3}>
              {p.manifest.description}
            </Text>
            <Group gap={4} mt="xs">
              <StatusBadge status={p.status} />
              {p.health && p.health.state !== "ok" && <Badge color="orange">{p.health.detail ?? p.health.state}</Badge>}
              {p.manifest.types.map((t) => (
                <Badge key={t} size="xs" variant="outline">
                  {t}
                </Badge>
              ))}
            </Group>
            {p.error && (
              <Alert color="red" mt="xs" p="xs">
                <Text size="xs">{p.error}</Text>
              </Alert>
            )}
            {p.running && (p.provides.providers.length > 0 || p.provides.tools.length > 0) && (
              <Text size="xs" c="dimmed" mt="xs">
                Stellt bereit: {[...p.provides.providers, ...p.provides.tools].join(", ")}
              </Text>
            )}
            <Group mt="sm" gap="xs">
              <Button size="xs" variant="light" leftSection={<IconSettings size={14} />} onClick={() => setConfiguring(p)}>
                Konfigurieren
              </Button>
              {p.source !== "builtin" && (
                <Button size="xs" color="red" variant="subtle" leftSection={<IconTrash size={14} />} onClick={() => confirm(`${p.id} entfernen?`) && remove.mutate(p.id)}>
                  Entfernen
                </Button>
              )}
            </Group>
          </Card>
        ))}
      </SimpleGrid>
      {configuring && <ConfigModal plugin={configuring} onClose={() => setConfiguring(null)} />}
    </Stack>
  );
}
