import {
  Badge,
  Button,
  Card,
  Group,
  Image,
  Modal,
  MultiSelect,
  NumberInput,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Tabs,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { IconScan, IconTrash } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { useT } from "@/shared/i18n";

import { api, qs } from "@/shared/api";

import { PageHeader, fmtTime, useAction } from "../components/common";

interface Zone {
  name: string;
  points: [number, number][];
}
interface VisionConfig {
  enabled: boolean;
  fps: number;
  motion: boolean;
  objects: boolean;
  labels: string[];
  faces: boolean;
  min_score: number;
  privacy_zones: Zone[];
}
interface CameraInfo {
  device_id: string;
  name: string;
  room_id: string | null;
  config: VisionConfig;
  active: boolean;
  stats: {
    frames: number;
    analyzed: number;
    motion: boolean;
    tracks: number;
    fps: number;
    detect_ms: number;
  } | null;
}
interface Sighting {
  id: string;
  camera_device_id: string;
  room_id: string | null;
  label: string;
  person_id: string | null;
  person_name: string | null;
  first_seen: string;
  last_seen: string;
  best_score: number;
  identity_similarity: number | null;
}
interface Watch {
  id: string;
  name: string;
  camera_device_id: string;
  enabled: boolean;
  spec: {
    labels: string[];
    zone: Zone | null;
    min_score: number;
    cooldown_s: number;
  };
  created_by: string;
}
interface Analysis {
  detections: {
    label: string;
    score: number;
    bbox: { x: number; y: number; w: number; h: number };
  }[];
  faces: {
    bbox: { x: number; y: number; w: number; h: number };
    person_name: string | null;
    similarity: number | null;
    match_level: string | null;
  }[];
  image: string;
}

function ZoneEditor({
  camera,
  onClose,
}: {
  camera: CameraInfo;
  onClose: () => void;
}) {
  const [zones, setZones] = useState<Zone[]>(camera.config.privacy_zones);
  const t = useT();
  const [drag, setDrag] = useState<{ x: number; y: number } | null>(null);
  const [current, setCurrent] = useState<{
    x: number;
    y: number;
    w: number;
    h: number;
  } | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const save = useAction(
    () =>
      api.put(`/api/vision/cameras/${camera.device_id}`, {
        ...camera.config,
        privacy_zones: zones,
      }),
    {
      invalidate: [["vision-cameras"]],
      success: t("vis.zonesSaved"),
    },
  );
  const rel = (e: React.MouseEvent) => {
    const r = box.current!.getBoundingClientRect();
    return {
      x: (e.clientX - r.left) / r.width,
      y: (e.clientY - r.top) / r.height,
    };
  };
  return (
    <Modal
      opened
      onClose={onClose}
      title={t("vis.zonesTitle", { name: camera.name })}
      size="xl"
    >
      <Stack>
        <Text size="sm">{t("vis.zonesHint")}</Text>
        <div
          ref={box}
          style={{
            position: "relative",
            userSelect: "none",
            cursor: "crosshair",
          }}
          onMouseDown={(e) => setDrag(rel(e))}
          onMouseMove={(e) => {
            if (!drag) return;
            const p = rel(e);
            setCurrent({
              x: Math.min(drag.x, p.x),
              y: Math.min(drag.y, p.y),
              w: Math.abs(p.x - drag.x),
              h: Math.abs(p.y - drag.y),
            });
          }}
          onMouseUp={() => {
            if (current && current.w > 0.01 && current.h > 0.01) {
              const { x, y, w, h } = current;
              setZones([
                ...zones,
                {
                  name: t("vis.zone", { n: zones.length + 1 }),
                  points: [
                    [x, y],
                    [x + w, y],
                    [x + w, y + h],
                    [x, y + h],
                  ],
                },
              ]);
            }
            setDrag(null);
            setCurrent(null);
          }}
        >
          <Image
            src={`/api/devices/${camera.device_id}/snapshot.jpg`}
            draggable={false}
            alt={t("vis.cameraImage")}
          />
          {[
            ...zones.map((z) => ({
              x: z.points[0][0],
              y: z.points[0][1],
              w: z.points[2][0] - z.points[0][0],
              h: z.points[2][1] - z.points[0][1],
            })),
            ...(current ? [current] : []),
          ].map((r, i) => (
            <div
              key={i}
              style={{
                position: "absolute",
                left: `${r.x * 100}%`,
                top: `${r.y * 100}%`,
                width: `${r.w * 100}%`,
                height: `${r.h * 100}%`,
                background: "rgba(0,0,0,0.55)",
                border: "2px solid red",
              }}
            />
          ))}
        </div>
        <Group>
          {zones.map((z, i) => (
            <Badge
              key={i}
              rightSection={
                <IconTrash
                  size={12}
                  style={{ cursor: "pointer" }}
                  onClick={() => setZones(zones.filter((_, j) => j !== i))}
                />
              }
            >
              {z.name}
            </Badge>
          ))}
        </Group>
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

function CameraCard({ cam, labels }: { cam: CameraInfo; labels: string[] }) {
  const [cfg, setCfg] = useState<VisionConfig>(cam.config);
  const t = useT();
  const [zones, setZones] = useState(false);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const save = useAction(
    () => api.put(`/api/vision/cameras/${cam.device_id}`, cfg),
    { invalidate: [["vision-cameras"]], success: t("common.saved") },
  );
  const analyze = useAction(
    () =>
      api.post<Analysis>("/api/vision/analyze", { device_id: cam.device_id }),
    {},
  );
  return (
    <Card withBorder>
      <Group justify="space-between">
        <Title order={5}>{cam.name}</Title>
        {cam.active ? (
          <Badge color="blue">{t("vis.analysisActive")}</Badge>
        ) : (
          <Badge color="gray">{t("vis.inactive")}</Badge>
        )}
      </Group>
      {cam.stats && (
        <Text size="xs" c="dimmed">
          {t("vis.stats", {
            fps: cam.stats.fps.toFixed(1),
            analyzed: cam.stats.analyzed,
            frames: cam.stats.frames,
            ms: cam.stats.detect_ms.toFixed(0),
            tracks: cam.stats.tracks,
          })}
          {cam.stats.motion && t("vis.motionSuffix")}
        </Text>
      )}
      <Stack gap="xs" mt="sm">
        <Switch
          label={t("vis.enabled")}
          checked={cfg.enabled}
          onChange={(e) => setCfg({ ...cfg, enabled: e.currentTarget.checked })}
        />
        <Group grow>
          <Switch
            label={t("vis.motion")}
            checked={cfg.motion}
            onChange={(e) =>
              setCfg({ ...cfg, motion: e.currentTarget.checked })
            }
          />
          <Switch
            label={t("vis.objects")}
            checked={cfg.objects}
            onChange={(e) =>
              setCfg({ ...cfg, objects: e.currentTarget.checked })
            }
          />
          <Switch
            label={t("vis.faces")}
            checked={cfg.faces}
            onChange={(e) => setCfg({ ...cfg, faces: e.currentTarget.checked })}
          />
        </Group>
        <MultiSelect
          label={t("vis.labels")}
          searchable
          data={labels}
          value={cfg.labels}
          onChange={(v) => setCfg({ ...cfg, labels: v })}
        />
        <Group grow>
          <NumberInput
            label={t("vis.fps")}
            min={0.2}
            max={10}
            step={0.5}
            decimalScale={1}
            value={cfg.fps}
            onChange={(v) => setCfg({ ...cfg, fps: Number(v) })}
          />
          <NumberInput
            label={t("vis.minScore")}
            min={0.1}
            max={0.95}
            step={0.05}
            decimalScale={2}
            value={cfg.min_score}
            onChange={(v) => setCfg({ ...cfg, min_score: Number(v) })}
          />
        </Group>
        <Group>
          <Button
            size="xs"
            onClick={() => save.mutate(undefined)}
            loading={save.isPending}
          >
            {t("common.save")}
          </Button>
          <Button size="xs" variant="light" onClick={() => setZones(true)}>
            {t("vis.zones", { n: cfg.privacy_zones.length })}
          </Button>
          <Button
            size="xs"
            variant="light"
            leftSection={<IconScan size={14} />}
            loading={analyze.isPending}
            onClick={async () =>
              setAnalysis(await analyze.mutateAsync(undefined))
            }
          >
            {t("vis.analyzeNow")}
          </Button>
        </Group>
        {analysis && (
          <Stack gap={4}>
            <Image src={analysis.image} radius="sm" alt={t("vis.analysis")} />
            <Group gap={4}>
              {analysis.detections.map((d, i) => (
                <Badge key={i} variant="light">
                  {d.label} {(d.score * 100).toFixed(0)} %
                </Badge>
              ))}
              {analysis.faces.map((f, i) => (
                <Badge key={`f${i}`} color="teal">
                  {t("vis.faceBadge", {
                    name: f.person_name ?? t("vis.unknown"),
                  })}{" "}
                  {f.similarity !== null &&
                    `(${f.similarity.toFixed(2)}, ${f.match_level})`}
                </Badge>
              ))}
            </Group>
          </Stack>
        )}
      </Stack>
      {zones && (
        <ZoneEditor
          camera={{ ...cam, config: cfg }}
          onClose={() => setZones(false)}
        />
      )}
    </Card>
  );
}

function Watches({
  cameras,
  labels,
}: {
  cameras: CameraInfo[];
  labels: string[];
}) {
  const watches = useQuery({
    queryKey: ["watches"],
    queryFn: () => api.get<Watch[]>("/api/vision/watches"),
  });
  const [name, setName] = useState("");
  const t = useT();
  const [camera, setCamera] = useState<string | null>(null);
  const [selLabels, setSelLabels] = useState<string[]>([]);
  const create = useAction(
    () =>
      api.post("/api/vision/watches", {
        name,
        camera_device_id: camera,
        labels: selLabels,
      }),
    {
      invalidate: [["watches"]],
      success: t("vis.watchCreated"),
    },
  );
  const del = useAction((id: string) => api.del(`/api/vision/watches/${id}`), {
    invalidate: [["watches"]],
  });
  return (
    <Stack>
      <Card withBorder>
        <Group align="flex-end">
          <TextInput
            label={t("common.name")}
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
            placeholder={t("vis.watchPlaceholder")}
          />
          <Select
            label={t("ppl.camera")}
            data={cameras.map((c) => ({ value: c.device_id, label: c.name }))}
            value={camera}
            onChange={setCamera}
          />
          <MultiSelect
            label={t("vis.objects")}
            data={labels}
            value={selLabels}
            onChange={setSelLabels}
            w={260}
          />
          <Button
            onClick={() => create.mutate(undefined)}
            disabled={!name || !camera || !selLabels.length}
          >
            {t("vis.create")}
          </Button>
        </Group>
        <Text size="xs" c="dimmed" mt="xs">
          {t("vis.watchHint")}
        </Text>
      </Card>
      <Table>
        <Table.Tbody>
          {watches.data?.map((w) => (
            <Table.Tr key={w.id}>
              <Table.Td>{w.name}</Table.Td>
              <Table.Td>
                {cameras.find((c) => c.device_id === w.camera_device_id)?.name}
              </Table.Td>
              <Table.Td>{w.spec.labels.join(", ")}</Table.Td>
              <Table.Td>{w.created_by}</Table.Td>
              <Table.Td>
                <Button
                  size="compact-xs"
                  color="red"
                  variant="subtle"
                  onClick={() => del.mutate(w.id)}
                >
                  {t("common.delete")}
                </Button>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}

export function VisionPage() {
  const cameras = useQuery({
    queryKey: ["vision-cameras"],
    queryFn: () => api.get<CameraInfo[]>("/api/vision/cameras"),
    refetchInterval: 5000,
  });
  const labels = useQuery({
    queryKey: ["vision-labels"],
    queryFn: () => api.get<string[]>("/api/vision/labels"),
  });
  const [label, setLabel] = useState<string | null>(null);
  const sightings = useQuery({
    queryKey: ["sightings", label],
    queryFn: () =>
      api.get<Sighting[]>(`/api/vision/sightings${qs({ label, limit: 100 })}`),
    refetchInterval: 10000,
  });
  const camName = (id: string) =>
    cameras.data?.find((c) => c.device_id === id)?.name ?? id;
  const t = useT();
  return (
    <Stack>
      <PageHeader title={t("nav.vision")} description={t("vis.desc")} />
      <Tabs defaultValue="cameras">
        <Tabs.List>
          <Tabs.Tab value="cameras">{t("vis.tabCameras")}</Tabs.Tab>
          <Tabs.Tab value="sightings">{t("vis.tabSightings")}</Tabs.Tab>
          <Tabs.Tab value="watches">{t("vis.tabWatches")}</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="cameras" pt="md">
          <SimpleGrid cols={{ base: 1, lg: 2 }}>
            {cameras.data?.map((c) => (
              <CameraCard
                key={c.device_id}
                cam={c}
                labels={labels.data ?? []}
              />
            ))}
          </SimpleGrid>
        </Tabs.Panel>
        <Tabs.Panel value="sightings" pt="md">
          <Select
            placeholder={t("vis.objectClass")}
            clearable
            searchable
            data={labels.data ?? []}
            value={label}
            onChange={setLabel}
            w={240}
            mb="sm"
          />
          <Table striped>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t("vis.what")}</Table.Th>
                <Table.Th>{t("ppl.camera")}</Table.Th>
                <Table.Th>{t("vis.from")}</Table.Th>
                <Table.Th>{t("vis.until")}</Table.Th>
                <Table.Th>{t("vis.score")}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {sightings.data?.map((s) => (
                <Table.Tr key={s.id}>
                  <Table.Td>
                    {s.label}{" "}
                    {s.person_name && (
                      <Badge color="teal">{s.person_name}</Badge>
                    )}
                  </Table.Td>
                  <Table.Td>{camName(s.camera_device_id)}</Table.Td>
                  <Table.Td>{fmtTime(s.first_seen)}</Table.Td>
                  <Table.Td>{fmtTime(s.last_seen)}</Table.Td>
                  <Table.Td>
                    {s.best_score.toFixed(2)}
                    {s.identity_similarity !== null &&
                      t("vis.similarity", {
                        v: s.identity_similarity.toFixed(2),
                      })}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Tabs.Panel>
        <Tabs.Panel value="watches" pt="md">
          <Watches cameras={cameras.data ?? []} labels={labels.data ?? []} />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
