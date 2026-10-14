import { Badge, Button, Card, Group, Image, Modal, MultiSelect, NumberInput, Select, SimpleGrid, Stack, Switch, Table, Tabs, Text, TextInput, Title } from "@mantine/core";
import { IconScan, IconTrash } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";

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
  stats: { frames: number; analyzed: number; motion: boolean; tracks: number; fps: number; detect_ms: number } | null;
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
  spec: { labels: string[]; zone: Zone | null; min_score: number; cooldown_s: number };
  created_by: string;
}
interface Analysis {
  detections: { label: string; score: number; bbox: { x: number; y: number; w: number; h: number } }[];
  faces: { bbox: { x: number; y: number; w: number; h: number }; person_name: string | null; similarity: number | null; match_level: string | null }[];
  image: string;
}

function ZoneEditor({ camera, onClose }: { camera: CameraInfo; onClose: () => void }) {
  const [zones, setZones] = useState<Zone[]>(camera.config.privacy_zones);
  const [drag, setDrag] = useState<{ x: number; y: number } | null>(null);
  const [current, setCurrent] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const save = useAction(() => api.put(`/api/vision/cameras/${camera.device_id}`, { ...camera.config, privacy_zones: zones }), {
    invalidate: [["vision-cameras"]],
    success: "Privatsphärenzonen gespeichert",
  });
  const rel = (e: React.MouseEvent) => {
    const r = box.current!.getBoundingClientRect();
    return { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height };
  };
  return (
    <Modal opened onClose={onClose} title={`Privatsphärenzonen: ${camera.name}`} size="xl">
      <Stack>
        <Text size="sm">Rechtecke aufziehen: Diese Bereiche werden vor jeder Analyse geschwärzt und nie ausgewertet.</Text>
        <div
          ref={box}
          style={{ position: "relative", userSelect: "none", cursor: "crosshair" }}
          onMouseDown={(e) => setDrag(rel(e))}
          onMouseMove={(e) => {
            if (!drag) return;
            const p = rel(e);
            setCurrent({ x: Math.min(drag.x, p.x), y: Math.min(drag.y, p.y), w: Math.abs(p.x - drag.x), h: Math.abs(p.y - drag.y) });
          }}
          onMouseUp={() => {
            if (current && current.w > 0.01 && current.h > 0.01) {
              const { x, y, w, h } = current;
              setZones([...zones, { name: `Zone ${zones.length + 1}`, points: [[x, y], [x + w, y], [x + w, y + h], [x, y + h]] }]);
            }
            setDrag(null);
            setCurrent(null);
          }}
        >
          <Image src={`/api/devices/${camera.device_id}/snapshot.jpg`} draggable={false} alt="Kamerabild" />
          {[...zones.map((z) => ({ x: z.points[0][0], y: z.points[0][1], w: z.points[2][0] - z.points[0][0], h: z.points[2][1] - z.points[0][1] })), ...(current ? [current] : [])].map(
            (r, i) => (
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
            ),
          )}
        </div>
        <Group>
          {zones.map((z, i) => (
            <Badge key={i} rightSection={<IconTrash size={12} style={{ cursor: "pointer" }} onClick={() => setZones(zones.filter((_, j) => j !== i))} />}>
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
          Speichern
        </Button>
      </Stack>
    </Modal>
  );
}

function CameraCard({ cam, labels }: { cam: CameraInfo; labels: string[] }) {
  const [cfg, setCfg] = useState<VisionConfig>(cam.config);
  const [zones, setZones] = useState(false);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const save = useAction(() => api.put(`/api/vision/cameras/${cam.device_id}`, cfg), { invalidate: [["vision-cameras"]], success: "Gespeichert" });
  const analyze = useAction(() => api.post<Analysis>("/api/vision/analyze", { device_id: cam.device_id }), {});
  return (
    <Card withBorder>
      <Group justify="space-between">
        <Title order={5}>{cam.name}</Title>
        {cam.active ? <Badge color="blue">Analyse aktiv</Badge> : <Badge color="gray">inaktiv</Badge>}
      </Group>
      {cam.stats && (
        <Text size="xs" c="dimmed">
          {cam.stats.fps.toFixed(1)} fps · {cam.stats.analyzed}/{cam.stats.frames} Frames analysiert · Detektor {cam.stats.detect_ms.toFixed(0)} ms ·{" "}
          {cam.stats.tracks} Objekte {cam.stats.motion && "· Bewegung"}
        </Text>
      )}
      <Stack gap="xs" mt="sm">
        <Switch label="Bildanalyse aktiv" checked={cfg.enabled} onChange={(e) => setCfg({ ...cfg, enabled: e.currentTarget.checked })} />
        <Group grow>
          <Switch label="Bewegung" checked={cfg.motion} onChange={(e) => setCfg({ ...cfg, motion: e.currentTarget.checked })} />
          <Switch label="Objekte" checked={cfg.objects} onChange={(e) => setCfg({ ...cfg, objects: e.currentTarget.checked })} />
          <Switch label="Gesichter" checked={cfg.faces} onChange={(e) => setCfg({ ...cfg, faces: e.currentTarget.checked })} />
        </Group>
        <MultiSelect label="Relevante Objektklassen" searchable data={labels} value={cfg.labels} onChange={(v) => setCfg({ ...cfg, labels: v })} />
        <Group grow>
          <NumberInput label="Analyse-FPS" min={0.2} max={10} step={0.5} decimalScale={1} value={cfg.fps} onChange={(v) => setCfg({ ...cfg, fps: Number(v) })} />
          <NumberInput label="Mindest-Score" min={0.1} max={0.95} step={0.05} decimalScale={2} value={cfg.min_score} onChange={(v) => setCfg({ ...cfg, min_score: Number(v) })} />
        </Group>
        <Group>
          <Button size="xs" onClick={() => save.mutate(undefined)} loading={save.isPending}>
            Speichern
          </Button>
          <Button size="xs" variant="light" onClick={() => setZones(true)}>
            Privatsphärenzonen ({cfg.privacy_zones.length})
          </Button>
          <Button
            size="xs"
            variant="light"
            leftSection={<IconScan size={14} />}
            loading={analyze.isPending}
            onClick={async () => setAnalysis(await analyze.mutateAsync(undefined))}
          >
            Jetzt analysieren
          </Button>
        </Group>
        {analysis && (
          <Stack gap={4}>
            <Image src={analysis.image} radius="sm" alt="Analyse" />
            <Group gap={4}>
              {analysis.detections.map((d, i) => (
                <Badge key={i} variant="light">
                  {d.label} {(d.score * 100).toFixed(0)} %
                </Badge>
              ))}
              {analysis.faces.map((f, i) => (
                <Badge key={`f${i}`} color="teal">
                  Gesicht: {f.person_name ?? "unbekannt"} {f.similarity !== null && `(${f.similarity.toFixed(2)}, ${f.match_level})`}
                </Badge>
              ))}
            </Group>
          </Stack>
        )}
      </Stack>
      {zones && <ZoneEditor camera={{ ...cam, config: cfg }} onClose={() => setZones(false)} />}
    </Card>
  );
}

function Watches({ cameras, labels }: { cameras: CameraInfo[]; labels: string[] }) {
  const watches = useQuery({ queryKey: ["watches"], queryFn: () => api.get<Watch[]>("/api/vision/watches") });
  const [name, setName] = useState("");
  const [camera, setCamera] = useState<string | null>(null);
  const [selLabels, setSelLabels] = useState<string[]>([]);
  const create = useAction(() => api.post("/api/vision/watches", { name, camera_device_id: camera, labels: selLabels }), {
    invalidate: [["watches"]],
    success: "Überwachung angelegt",
  });
  const del = useAction((id: string) => api.del(`/api/vision/watches/${id}`), { invalidate: [["watches"]] });
  return (
    <Stack>
      <Card withBorder>
        <Group align="flex-end">
          <TextInput label="Name" value={name} onChange={(e) => setName(e.currentTarget.value)} placeholder="Auto in der Einfahrt" />
          <Select label="Kamera" data={cameras.map((c) => ({ value: c.device_id, label: c.name }))} value={camera} onChange={setCamera} />
          <MultiSelect label="Objekte" data={labels} value={selLabels} onChange={setSelLabels} w={260} />
          <Button onClick={() => create.mutate(undefined)} disabled={!name || !camera || !selLabels.length}>
            Anlegen
          </Button>
        </Group>
        <Text size="xs" c="dimmed" mt="xs">
          Überwachungen erzeugen das Ereignis vision.watch.triggered – damit lassen sich Automationen auslösen.
        </Text>
      </Card>
      <Table>
        <Table.Tbody>
          {watches.data?.map((w) => (
            <Table.Tr key={w.id}>
              <Table.Td>{w.name}</Table.Td>
              <Table.Td>{cameras.find((c) => c.device_id === w.camera_device_id)?.name}</Table.Td>
              <Table.Td>{w.spec.labels.join(", ")}</Table.Td>
              <Table.Td>{w.created_by}</Table.Td>
              <Table.Td>
                <Button size="compact-xs" color="red" variant="subtle" onClick={() => del.mutate(w.id)}>
                  Löschen
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
  const cameras = useQuery({ queryKey: ["vision-cameras"], queryFn: () => api.get<CameraInfo[]>("/api/vision/cameras"), refetchInterval: 5000 });
  const labels = useQuery({ queryKey: ["vision-labels"], queryFn: () => api.get<string[]>("/api/vision/labels") });
  const [label, setLabel] = useState<string | null>(null);
  const sightings = useQuery({
    queryKey: ["sightings", label],
    queryFn: () => api.get<Sighting[]>(`/api/vision/sightings${qs({ label, limit: 100 })}`),
    refetchInterval: 10000,
  });
  const camName = (id: string) => cameras.data?.find((c) => c.device_id === id)?.name ?? id;
  return (
    <Stack>
      <PageHeader title="Vision" description="Mehrstufige, ressourcenschonende Bildanalyse: Bewegung → Objekte → Gesichter → Ereignisse" />
      <Tabs defaultValue="cameras">
        <Tabs.List>
          <Tabs.Tab value="cameras">Kameras</Tabs.Tab>
          <Tabs.Tab value="sightings">Sichtungen</Tabs.Tab>
          <Tabs.Tab value="watches">Überwachungen</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="cameras" pt="md">
          <SimpleGrid cols={{ base: 1, lg: 2 }}>
            {cameras.data?.map((c) => <CameraCard key={c.device_id} cam={c} labels={labels.data ?? []} />)}
          </SimpleGrid>
        </Tabs.Panel>
        <Tabs.Panel value="sightings" pt="md">
          <Select placeholder="Objektklasse" clearable searchable data={labels.data ?? []} value={label} onChange={setLabel} w={240} mb="sm" />
          <Table striped>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Was</Table.Th>
                <Table.Th>Kamera</Table.Th>
                <Table.Th>Von</Table.Th>
                <Table.Th>Bis</Table.Th>
                <Table.Th>Score</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {sightings.data?.map((s) => (
                <Table.Tr key={s.id}>
                  <Table.Td>
                    {s.label} {s.person_name && <Badge color="teal">{s.person_name}</Badge>}
                  </Table.Td>
                  <Table.Td>{camName(s.camera_device_id)}</Table.Td>
                  <Table.Td>{fmtTime(s.first_seen)}</Table.Td>
                  <Table.Td>{fmtTime(s.last_seen)}</Table.Td>
                  <Table.Td>
                    {s.best_score.toFixed(2)}
                    {s.identity_similarity !== null && ` / Ähnlichkeit ${s.identity_similarity.toFixed(2)}`}
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
