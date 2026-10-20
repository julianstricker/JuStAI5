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
import {
  IconPlus,
  IconRadar,
  IconRefresh,
  IconVolume,
} from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/shared/api";
import { useT } from "@/shared/i18n";
import { LiveVideo } from "@/shared/render/LiveVideo";
import type { Device, Driver, Room } from "@/shared/types";

import { useIsAdmin } from "../auth";
import { JsonSchemaForm } from "../components/JsonSchemaForm";
import {
  Json,
  PageHeader,
  StatusBadge,
  errorMessage,
  fmtTime,
  useAction,
} from "../components/common";
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

function AddDeviceModal({
  initial,
  onClose,
}: {
  initial?: Partial<{
    driver_id: string;
    config: Record<string, unknown>;
    name: string;
  }>;
  onClose: () => void;
}) {
  const drivers = useQuery({
    queryKey: ["drivers"],
    queryFn: () => api.get<Driver[]>("/api/devices/drivers"),
  });
  const rooms = useQuery({
    queryKey: ["rooms"],
    queryFn: () => api.get<Room[]>("/api/rooms"),
  });
  const [driverId, setDriverId] = useState<string | null>(
    initial?.driver_id ?? null,
  );
  const t = useT();
  const [name, setName] = useState(initial?.name ?? "");
  const [room, setRoom] = useState<string | null>(null);
  const [config, setConfig] = useState<Record<string, unknown>>(
    initial?.config ?? {},
  );
  const [probe, setProbe] = useState<ProbeResult | null>(null);
  const [probeError, setProbeError] = useState<string | null>(null);
  const [probing, setProbing] = useState(false);
  const driver = drivers.data?.find((d) => d.id === driverId);
  const save = useAction(
    () =>
      api.post("/api/devices", {
        name,
        driver_id: driverId,
        room_id: room,
        config,
      }),
    {
      invalidate: [["devices"]],
      success: t("dev.created"),
    },
  );

  const test = async () => {
    setProbing(true);
    setProbeError(null);
    try {
      setProbe(
        await api.post<ProbeResult>("/api/devices/probe", {
          driver_id: driverId,
          config,
        }),
      );
    } catch (err) {
      setProbeError(errorMessage(err));
    } finally {
      setProbing(false);
    }
  };

  return (
    <Modal opened onClose={onClose} title={t("dev.add")} size="lg">
      <Stack>
        <Select
          label={t("dev.driver")}
          data={(drivers.data ?? []).map((d) => ({
            value: d.id,
            label: `${d.name} (${d.plugin_id})`,
          }))}
          value={driverId}
          onChange={setDriverId}
        />
        <TextInput
          label={t("common.name")}
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
          required
        />
        <Select
          label={t("common.room")}
          clearable
          data={(rooms.data ?? []).map((r) => ({ value: r.id, label: r.name }))}
          value={room}
          onChange={setRoom}
        />
        {driver && (
          <JsonSchemaForm
            schema={driver.config_schema}
            value={config}
            onChange={setConfig}
            secretFields={driver.secret_fields}
          />
        )}
        {probeError && <Alert color="red">{probeError}</Alert>}
        {probe && (
          <Alert
            color={probe.ok ? "green" : "red"}
            title={probe.ok ? t("dev.probeOk") : t("dev.probeFailed")}
          >
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
          <Button
            variant="default"
            onClick={test}
            loading={probing}
            disabled={!driver}
          >
            {t("dev.test")}
          </Button>
          <Button
            onClick={async () => {
              await save.mutateAsync(undefined);
              onClose();
            }}
            loading={save.isPending}
            disabled={!driver || !name}
          >
            {t("common.save")}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function DiscoveryModal({
  onAdd,
  onClose,
}: {
  onAdd: (d: Discovered) => void;
  onClose: () => void;
}) {
  const settings = useQuery({
    queryKey: ["discovery-settings"],
    queryFn: () => api.get<{ cidrs: string[] }>("/api/discovery/settings"),
  });
  const [cidrs, setCidrs] = useState<string | null>(null);
  const t = useT();
  const value = cidrs ?? settings.data?.cidrs.join(", ") ?? "";
  const scan = useAction(() =>
    api.post<Discovered[]>("/api/discovery/scan", {
      cidrs: value
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
    }),
  );
  return (
    <Modal opened onClose={onClose} title={t("dev.discovery")} size="xl">
      <Stack>
        <TextInput
          label={t("dev.cidrs")}
          description={t("dev.cidrsHint")}
          value={value}
          onChange={(e) => setCidrs(e.currentTarget.value)}
        />
        <Button
          leftSection={<IconRadar size={16} />}
          onClick={() => scan.mutate(undefined)}
          loading={scan.isPending}
        >
          {t("common.search")}
        </Button>
        <Table>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t("dev.host")}</Table.Th>
              <Table.Th>{t("dev.device")}</Table.Th>
              <Table.Th>{t("dev.protocols")}</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {scan.data?.map((d) => (
              <Table.Tr key={d.fingerprint}>
                <Table.Td>{d.host}</Table.Td>
                <Table.Td>
                  {d.manufacturer} {d.model}{" "}
                  {d.name && <Text size="xs">{d.name}</Text>}
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
                    <Badge color="green">{t("dev.known")}</Badge>
                  ) : (
                    <Button
                      size="xs"
                      disabled={!d.suggested_driver}
                      onClick={() => onAdd(d)}
                    >
                      {t("common.add")}
                    </Button>
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        {scan.data && !scan.data.length && (
          <Text c="dimmed">{t("dev.noneFound")}</Text>
        )}
      </Stack>
    </Modal>
  );
}

function DeviceDrawer({
  device,
  onClose,
}: {
  device: Device;
  onClose: () => void;
}) {
  const isAdmin = useIsAdmin();
  const t = useT();
  const [snapKey, setSnapKey] = useState(() => Date.now());
  const [live, setLive] = useState(true); // live by default; the switch falls back to snapshots
  const drivers = useQuery({
    queryKey: ["drivers"],
    queryFn: () => api.get<Driver[]>("/api/devices/drivers"),
  });
  const driver = drivers.data?.find((d) => d.id === device.driver_id);
  const [config, setConfig] = useState<Record<string, unknown>>(device.config);
  const [settingsText, setSettingsText] = useState(
    JSON.stringify(device.settings, null, 2),
  );
  const camera =
    device.capabilities.includes("video.input") ||
    device.capabilities.includes("camera.snapshot");
  const ptz = device.capabilities.includes("camera.ptz.pan");
  const tone = useAction(
    () => api.post(`/api/devices/${device.id}/test-tone`),
    { success: t("dev.tonePlayed") },
  );
  const reconnect = useAction(
    () => api.post(`/api/devices/${device.id}/reconnect`),
    { invalidate: [["devices"]], success: t("dev.reconnecting") },
  );
  const toggle = useAction(
    (enabled: boolean) => api.patch(`/api/devices/${device.id}`, { enabled }),
    { invalidate: [["devices"]] },
  );
  const saveConfig = useAction(
    () =>
      api.patch(`/api/devices/${device.id}`, {
        config,
        settings: JSON.parse(settingsText),
      }),
    {
      invalidate: [["devices"]],
      success: t("common.saved"),
    },
  );
  const del = useAction(() => api.del(`/api/devices/${device.id}`), {
    invalidate: [["devices"]],
    success: t("dev.deleted"),
  });

  return (
    <Drawer
      opened
      onClose={onClose}
      position="right"
      size="xl"
      title={device.name}
    >
      <Stack>
        <Group justify="space-between" align="flex-start">
          <Group>
            <StatusBadge status={device.status} />
            <Text size="sm" c="dimmed">
              {device.status_detail}
            </Text>
          </Group>
          {isAdmin && (
            <Switch
              label={t("dev.enabled")}
              description={device.enabled ? undefined : t("dev.keepsSettings")}
              checked={device.enabled}
              onChange={(e) => toggle.mutate(e.currentTarget.checked)}
            />
          )}
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
            {camera && <Tabs.Tab value="view">{t("dev.tabView")}</Tabs.Tab>}
            <Tabs.Tab value="config">{t("dev.tabConfig")}</Tabs.Tab>
            <Tabs.Tab value="info">{t("dev.tabInfo")}</Tabs.Tab>
          </Tabs.List>
          {camera && (
            <Tabs.Panel value="view" pt="sm">
              {!device.enabled ? (
                <Text c="dimmed">{t("dev.disabledHint")}</Text>
              ) : (
                <Stack>
                  {live ? (
                    device.status === "online" ? (
                      <LiveVideo
                        src={`/api/devices/${device.id}/live.${device.stream ? "mp4" : "mjpeg"}`}
                      />
                    ) : (
                      <Text c="dimmed">
                        {t("dev.cameraConnecting", { status: device.status })}
                      </Text>
                    )
                  ) : (
                    <Image
                      src={`/api/devices/${device.id}/snapshot.jpg?k=${snapKey}`}
                      radius="md"
                      alt={t("dev.snapshot")}
                      fallbackSrc=""
                    />
                  )}
                  <Group>
                    <Button
                      size="xs"
                      variant="default"
                      leftSection={<IconRefresh size={14} />}
                      onClick={() => setSnapKey(Date.now())}
                    >
                      {t("dev.newSnapshot")}
                    </Button>
                    <Switch
                      label={t("dev.liveVideo")}
                      checked={live}
                      onChange={(e) => setLive(e.currentTarget.checked)}
                    />
                  </Group>
                  {ptz && <PtzPad deviceId={device.id} />}
                </Stack>
              )}
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
                label={t("dev.settingsJson")}
                description={t("dev.settingsHint")}
                component="textarea"
                value={settingsText}
                onChange={(e) => setSettingsText(e.currentTarget.value)}
                styles={{ input: { minHeight: 100, fontFamily: "monospace" } }}
              />
              {isAdmin && (
                <Group>
                  <Button
                    onClick={() => saveConfig.mutate(undefined)}
                    loading={saveConfig.isPending}
                  >
                    {t("common.save")}
                  </Button>
                </Group>
              )}
            </Stack>
          </Tabs.Panel>
          <Tabs.Panel value="info" pt="sm">
            <Json
              value={{
                driver: device.driver_id,
                info: device.info,
                last_seen: fmtTime(device.last_seen_at),
                audio: device.audio,
              }}
            />
          </Tabs.Panel>
        </Tabs>
        {isAdmin && (
          <Group>
            {device.enabled && device.capabilities.includes("audio.output") && (
              <Button
                variant="light"
                leftSection={<IconVolume size={16} />}
                onClick={() => tone.mutate(undefined)}
                loading={tone.isPending}
              >
                {t("dev.testTone")}
              </Button>
            )}
            <Button
              variant="light"
              disabled={!device.enabled}
              onClick={() => reconnect.mutate(undefined)}
            >
              {t("dev.reconnect")}
            </Button>
            <Button
              color="red"
              variant="light"
              onClick={async () => {
                if (!confirm(t("dev.confirmDelete", { name: device.name })))
                  return;
                await del.mutateAsync(undefined);
                onClose();
              }}
            >
              {t("common.delete")}
            </Button>
          </Group>
        )}
      </Stack>
    </Drawer>
  );
}

export function DevicesPage() {
  const isAdmin = useIsAdmin();
  const t = useT();
  const devices = useQuery({
    queryKey: ["devices"],
    queryFn: () => api.get<Device[]>("/api/devices"),
    refetchInterval: 4000,
  });
  const rooms = useQuery({
    queryKey: ["rooms"],
    queryFn: () => api.get<Room[]>("/api/rooms"),
  });
  const [adding, setAdding] = useState<Partial<{
    driver_id: string;
    config: Record<string, unknown>;
    name: string;
  }> | null>(null);
  const [discover, setDiscover] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const roomName = (id: string | null) =>
    rooms.data?.find((r) => r.id === id)?.name ?? "–";
  const current = devices.data?.find((d) => d.id === selected);

  return (
    <Stack>
      <PageHeader
        title={t("nav.devices")}
        description={t("dev.desc")}
        actions={
          isAdmin && (
            <>
              <Button
                variant="default"
                leftSection={<IconRadar size={16} />}
                onClick={() => setDiscover(true)}
              >
                {t("common.search")}
              </Button>
              <Button
                leftSection={<IconPlus size={16} />}
                onClick={() => setAdding({})}
              >
                {t("dev.addShort")}
              </Button>
            </>
          )
        }
      />
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
        {devices.data?.map((d) => (
          <Card
            key={d.id}
            withBorder
            style={{ cursor: "pointer", opacity: d.enabled ? 1 : 0.55 }}
            onClick={() => setSelected(d.id)}
          >
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
      {devices.data && !devices.data.length && (
        <Text c="dimmed">{t("dev.none")}</Text>
      )}
      {adding && (
        <AddDeviceModal initial={adding} onClose={() => setAdding(null)} />
      )}
      {discover && (
        <DiscoveryModal
          onClose={() => setDiscover(false)}
          onAdd={(d) => {
            setDiscover(false);
            setAdding({
              driver_id: d.suggested_driver ?? undefined,
              config: d.suggested_config,
              name: d.name ?? `${d.manufacturer ?? ""} ${d.host}`.trim(),
            });
          }}
        />
      )}
      {current && (
        <DeviceDrawer
          key={current.id}
          device={current}
          onClose={() => setSelected(null)}
        />
      )}
    </Stack>
  );
}
