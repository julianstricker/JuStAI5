import {
  Alert,
  Badge,
  Button,
  Card,
  Drawer,
  Group,
  Image,
  Modal,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Tabs,
  Text,
  TextInput,
} from "@mantine/core";
import { IconPlus, IconRadar, IconRefresh, IconVolume } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/shared/api";
import type { Device, Driver, Room } from "@/shared/types";

import { useIsAdmin } from "../auth";
import { JsonSchemaForm } from "../components/JsonSchemaForm";
import { Json, PageHeader, StatusBadge, errorMessage, fmtTime, useAction } from "../components/common";
import { PtzPad } from "../components/PtzPad";

interface ProbeResult {
  ok: boolean;
  capabilities: string[];
  info: Record<string, unknown>;
  warnings: string[];
  error: string | null;
}

interface Discovered {
  fingerprint: string;
  host: string;
  name: string | null;
  manufacturer: string | null;
  model: string | null;
  protocols: string[];
  suggested_driver: string | null;
  suggested_config: Record<string, unknown>;
  requires_credentials: boolean;
  known_device_id: string | null;
}

function AddDeviceModal({ initial, onClose }: { initial?: Partial<{ driver_id: string; config: Record<string, unknown>; name: string }>; onClose: () => void }) {
  const drivers = useQuery({ queryKey: ["drivers"], queryFn: () => api.get<Driver[]>("/api/devices/drivers") });
  const rooms = useQuery({ queryKey: ["rooms"], queryFn: () => api.get<Room[]>("/api/rooms") });
  const [driverId, setDriverId] = useState<string | null>(initial?.driver_id ?? null);
  const [name, setName] = useState(initial?.name ?? "");
  const [room, setRoom] = useState<string | null>(null);
  const [config, setConfig] = useState<Record<string, unknown>>(initial?.config ?? {});
  const [probe, setProbe] = useState<ProbeResult | null>(null);
  const [probeError, setProbeError] = useState<string | null>(null);
  const [probing, setProbing] = useState(false);
  const driver = drivers.data?.find((d) => d.id === driverId);
  const save = useAction(() => api.post("/api/devices", { name, driver_id: driverId, room_id: room, config }), {
    invalidate: [["devices"]],
    success: "Gerät angelegt",
  });

  const test = async () => {
    setProbing(true);
    setProbeError(null);
    try {
      setProbe(await api.post<ProbeResult>("/api/devices/probe", { driver_id: driverId, config }));
    } catch (err) {
      setProbeError(errorMessage(err));
    } finally {
      setProbing(false);
    }
  };

  return (
    <Modal opened onClose={onClose} title="Gerät hinzufügen" size="lg">
      <Stack>
        <Select label="Treiber" data={(drivers.data ?? []).map((d) => ({ value: d.id, label: `${d.name} (${d.plugin_id})` }))} value={driverId} onChange={setDriverId} />
        <TextInput label="Name" value={name} onChange={(e) => setName(e.currentTarget.value)} required />
        <Select label="Raum" clearable data={(rooms.data ?? []).map((r) => ({ value: r.id, label: r.name }))} value={room} onChange={setRoom} />
        {driver && <JsonSchemaForm schema={driver.config_schema} value={config} onChange={setConfig} secretFields={driver.secret_fields} />}
        {probeError && <Alert color="red">{probeError}</Alert>}
        {probe && (
          <Alert color={probe.ok ? "green" : "red"} title={probe.ok ? "Verbindung erfolgreich" : "Verbindung fehlgeschlagen"}>
            {probe.error}
            {probe.ok && (
              <Group gap={4} mt={4}>
                {probe.capabilities.map((c) => (
                  <Badge key={c} size="xs">
                    {c}
                  </Badge>
                ))}
              </Group>
            )}
            {probe.warnings.map((w) => (
              <Text key={w} size="xs" mt={4}>
                ⚠ {w}
              </Text>
            ))}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={test} loading={probing} disabled={!driver}>
            Verbindung testen
          </Button>
          <Button
            onClick={async () => {
              await save.mutateAsync(undefined);
              onClose();
            }}
            loading={save.isPending}
            disabled={!driver || !name}
          >
            Speichern
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function DiscoveryModal({ onAdd, onClose }: { onAdd: (d: Discovered) => void; onClose: () => void }) {
  const settings = useQuery({ queryKey: ["discovery-settings"], queryFn: () => api.get<{ cidrs: string[] }>("/api/discovery/settings") });
  const [cidrs, setCidrs] = useState<string | null>(null);
  const value = cidrs ?? settings.data?.cidrs.join(", ") ?? "";
  const scan = useAction(() => api.post<Discovered[]>("/api/discovery/scan", { cidrs: value.split(",").map((s) => s.trim()).filter(Boolean) }));
  return (
    <Modal opened onClose={onClose} title="Gerätesuche" size="xl">
      <Stack>
        <TextInput
          label="Autorisierte Netzbereiche (CIDR)"
          description="Es wird ausschließlich in diesen Bereichen gesucht."
          value={value}
          onChange={(e) => setCidrs(e.currentTarget.value)}
        />
        <Button leftSection={<IconRadar size={16} />} onClick={() => scan.mutate(undefined)} loading={scan.isPending}>
          Suchen
        </Button>
        <Table>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Host</Table.Th>
              <Table.Th>Gerät</Table.Th>
              <Table.Th>Protokolle</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {scan.data?.map((d) => (
              <Table.Tr key={d.fingerprint}>
                <Table.Td>{d.host}</Table.Td>
                <Table.Td>
                  {d.manufacturer} {d.model} {d.name && <Text size="xs">{d.name}</Text>}
                </Table.Td>
                <Table.Td>
                  {d.protocols.map((p) => (
                    <Badge key={p} size="xs" mr={2}>
                      {p}
                    </Badge>
                  ))}
                </Table.Td>
                <Table.Td>
                  {d.known_device_id ? (
                    <Badge color="green">bereits angelegt</Badge>
                  ) : (
                    <Button size="xs" disabled={!d.suggested_driver} onClick={() => onAdd(d)}>
                      Hinzufügen
                    </Button>
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        {scan.data && !scan.data.length && <Text c="dimmed">Keine Geräte gefunden.</Text>}
      </Stack>
    </Modal>
  );
}

function DeviceDrawer({ device, onClose }: { device: Device; onClose: () => void }) {
  const isAdmin = useIsAdmin();
  const [snapKey, setSnapKey] = useState(Date.now());
  const [live, setLive] = useState(false);
  const drivers = useQuery({ queryKey: ["drivers"], queryFn: () => api.get<Driver[]>("/api/devices/drivers") });
  const driver = drivers.data?.find((d) => d.id === device.driver_id);
  const [config, setConfig] = useState<Record<string, unknown>>(device.config);
  const [settingsText, setSettingsText] = useState(JSON.stringify(device.settings, null, 2));
  const camera = device.capabilities.includes("video.input") || device.capabilities.includes("camera.snapshot");
  const ptz = device.capabilities.includes("camera.ptz.pan");
  const tone = useAction(() => api.post(`/api/devices/${device.id}/test-tone`), { success: "Testton abgespielt" });
  const reconnect = useAction(() => api.post(`/api/devices/${device.id}/reconnect`), { invalidate: [["devices"]], success: "Verbindung wird neu aufgebaut" });
  const toggle = useAction((enabled: boolean) => api.patch(`/api/devices/${device.id}`, { enabled }), { invalidate: [["devices"]] });
  const saveConfig = useAction(() => api.patch(`/api/devices/${device.id}`, { config, settings: JSON.parse(settingsText) }), {
    invalidate: [["devices"]],
    success: "Gespeichert",
  });
  const del = useAction(() => api.del(`/api/devices/${device.id}`), { invalidate: [["devices"]], success: "Gerät gelöscht" });

  return (
    <Drawer opened onClose={onClose} position="right" size="xl" title={device.name}>
      <Stack>
        <Group>
          <StatusBadge status={device.status} />
          <Text size="sm" c="dimmed">
            {device.status_detail}
          </Text>
        </Group>
        <Group gap={4}>
          {device.capabilities.map((c) => (
            <Badge key={c} variant="light">
              {c}
            </Badge>
          ))}
        </Group>
        <Tabs defaultValue={camera ? "view" : "config"}>
          <Tabs.List>
            {camera && <Tabs.Tab value="view">Bild</Tabs.Tab>}
            <Tabs.Tab value="config">Konfiguration</Tabs.Tab>
            <Tabs.Tab value="info">Info</Tabs.Tab>
          </Tabs.List>
          {camera && (
            <Tabs.Panel value="view" pt="sm">
              <Stack>
                {live ? (
                  <video src={`/api/devices/${device.id}/live.mp4`} autoPlay muted playsInline style={{ width: "100%", borderRadius: 8 }} />
                ) : (
                  <Image src={`/api/devices/${device.id}/snapshot.jpg?k=${snapKey}`} radius="md" alt="Snapshot" fallbackSrc="" />
                )}
                <Group>
                  <Button size="xs" variant="default" leftSection={<IconRefresh size={14} />} onClick={() => setSnapKey(Date.now())}>
                    Neuer Snapshot
                  </Button>
                  <Switch label="Live-Video" checked={live} onChange={(e) => setLive(e.currentTarget.checked)} />
                </Group>
                {ptz && <PtzPad deviceId={device.id} />}
              </Stack>
            </Tabs.Panel>
          )}
          <Tabs.Panel value="config" pt="sm">
            <Stack>
              {driver && (
                <JsonSchemaForm
                  schema={driver.config_schema}
                  value={config}
                  onChange={setConfig}
                  secretFields={driver.secret_fields}
                  secretsSet={device.secret_fields_set}
                />
              )}
              <TextInput
                label="Geräte-Einstellungen (JSON)"
                description="z. B. output_latency_s, preferred_output, Vision-/PTZ-Grenzen"
                component="textarea"
                value={settingsText}
                onChange={(e) => setSettingsText(e.currentTarget.value)}
                styles={{ input: { minHeight: 100, fontFamily: "monospace" } }}
              />
              {isAdmin && (
                <Group>
                  <Button onClick={() => saveConfig.mutate(undefined)} loading={saveConfig.isPending}>
                    Speichern
                  </Button>
                  <Switch label="Aktiviert" checked={device.enabled} onChange={(e) => toggle.mutate(e.currentTarget.checked)} />
                </Group>
              )}
            </Stack>
          </Tabs.Panel>
          <Tabs.Panel value="info" pt="sm">
            <Json value={{ driver: device.driver_id, info: device.info, last_seen: fmtTime(device.last_seen_at), audio: device.audio }} />
          </Tabs.Panel>
        </Tabs>
        {isAdmin && (
          <Group>
            {device.capabilities.includes("audio.output") && (
              <Button variant="light" leftSection={<IconVolume size={16} />} onClick={() => tone.mutate(undefined)} loading={tone.isPending}>
                Testton
              </Button>
            )}
            <Button variant="light" onClick={() => reconnect.mutate(undefined)}>
              Neu verbinden
            </Button>
            <Button
              color="red"
              variant="light"
              onClick={async () => {
                if (!confirm(`${device.name} löschen?`)) return;
                await del.mutateAsync(undefined);
                onClose();
              }}
            >
              Löschen
            </Button>
          </Group>
        )}
      </Stack>
    </Drawer>
  );
}

export function DevicesPage() {
  const isAdmin = useIsAdmin();
  const devices = useQuery({ queryKey: ["devices"], queryFn: () => api.get<Device[]>("/api/devices"), refetchInterval: 4000 });
  const rooms = useQuery({ queryKey: ["rooms"], queryFn: () => api.get<Room[]>("/api/rooms") });
  const [adding, setAdding] = useState<Partial<{ driver_id: string; config: Record<string, unknown>; name: string }> | null>(null);
  const [discover, setDiscover] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const roomName = (id: string | null) => rooms.data?.find((r) => r.id === id)?.name ?? "–";
  const current = devices.data?.find((d) => d.id === selected);

  return (
    <Stack>
      <PageHeader
        title="Geräte"
        description="Kameras, Mikrofone, Lautsprecher, Displays und Sensoren. Fähigkeiten werden zur Laufzeit ermittelt."
        actions={
          isAdmin && (
            <>
              <Button variant="default" leftSection={<IconRadar size={16} />} onClick={() => setDiscover(true)}>
                Suchen
              </Button>
              <Button leftSection={<IconPlus size={16} />} onClick={() => setAdding({})}>
                Gerät
              </Button>
            </>
          )
        }
      />
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
        {devices.data?.map((d) => (
          <Card key={d.id} withBorder style={{ cursor: "pointer" }} onClick={() => setSelected(d.id)}>
            <Group justify="space-between">
              <Text fw={600}>{d.name}</Text>
              <StatusBadge status={d.status} />
            </Group>
            <Text size="xs" c="dimmed">
              {d.driver_id} · {roomName(d.room_id)}
            </Text>
            {d.status_detail && (
              <Text size="xs" c="orange">
                {d.status_detail}
              </Text>
            )}
            <Group gap={4} mt="xs">
              {d.capabilities.map((c) => (
                <Badge key={c} size="xs" variant="outline">
                  {c}
                </Badge>
              ))}
            </Group>
          </Card>
        ))}
      </SimpleGrid>
      {devices.data && !devices.data.length && <Text c="dimmed">Noch keine Geräte. Starte eine Suche oder lege ein Gerät manuell an.</Text>}
      {adding && <AddDeviceModal initial={adding} onClose={() => setAdding(null)} />}
      {discover && (
        <DiscoveryModal
          onClose={() => setDiscover(false)}
          onAdd={(d) => {
            setDiscover(false);
            setAdding({ driver_id: d.suggested_driver ?? undefined, config: d.suggested_config, name: d.name ?? `${d.manufacturer ?? ""} ${d.host}`.trim() });
          }}
        />
      )}
      {current && <DeviceDrawer key={current.id} device={current} onClose={() => setSelected(null)} />}
    </Stack>
  );
}
