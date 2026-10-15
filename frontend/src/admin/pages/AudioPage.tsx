import { Badge, Button, Card, Group, NumberInput, Progress, SimpleGrid, Stack, Table, Text, Title } from "@mantine/core";
import { IconDownload } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/shared/api";
import { useLiveEvents, useTelemetry } from "@/shared/live";
import type { Device, Endpoint, EndpointRuntime } from "@/shared/types";

import { useIsAdmin } from "../auth";
import { PageHeader, fmtTime, notifyError } from "../components/common";

interface MicTelemetry {
  level_db: number;
  chunks: number;
  overruns: number;
  stale_s: number | null;
}

interface SpeakerTelemetry {
  playing: boolean;
  frames: number;
  underruns: number;
  latency_s: number;
  utterance: string | null;
  talkback?: { connected: boolean; connections: number; bytes_pulled: number; dropped_frames: number };
}

const toPct = (db: number) => Math.max(0, Math.min(100, ((db + 90) / 90) * 100));

function Meter({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <Stack gap={2}>
      <Group justify="space-between">
        <Text size="xs">{label}</Text>
        <Text size="xs" ff="monospace">
          {value.toFixed(1)} dBFS
        </Text>
      </Group>
      <Progress value={toPct(value)} color={color} transitionDuration={150} />
    </Stack>
  );
}

function EndpointCard({ ep, rt }: { ep: Endpoint; rt?: EndpointRuntime }) {
  const isAdmin = useIsAdmin();
  const [seconds, setSeconds] = useState(10);
  const [recording, setRecording] = useState(false);
  const record = async () => {
    setRecording(true);
    try {
      const blob = await api.post<Blob>(`/api/endpoints/${ep.id}/diagnostic-recording`, { seconds });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${ep.name}-diagnose.wav`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      notifyError(err);
    } finally {
      setRecording(false);
    }
  };
  const r = rt ?? ep.runtime;
  const hasMic = ep.devices.some((d) => d.role === "mic");
  if (!hasMic) {
    return (
      <Card withBorder>
        <Title order={5}>{ep.name}</Title>
        <Text size="sm" c="dimmed" mt="xs">
          Kein Mikrofon zugeordnet – das Gerät wurde gelöscht oder nie zugewiesen. Unter „Räume“ ein Mikrofon zuordnen oder den
          Endpoint löschen.
        </Text>
      </Card>
    );
  }
  return (
    <Card withBorder>
      <Group justify="space-between" mb="xs">
        <Title order={5}>{ep.name}</Title>
        <Group gap={4}>
          {r?.gated && <Badge color="orange">Eingang gesperrt</Badge>}
          {r?.echo_window && <Badge color="violet">Echofenster</Badge>}
          {r?.speech && <Badge color="green">Sprache</Badge>}
          <Badge variant="outline">{r?.duplex === "full" ? "Vollduplex" : "Halbduplex"}</Badge>
        </Group>
      </Group>
      {r ? (
        <Stack gap="xs">
          <Meter label="Mikrofon (verarbeitet)" value={r.level_db} />
          <Meter label="Grundrauschen" value={r.noise_floor_db} color="gray" />
          <Group grow>
            <Stack gap={2}>
              <Text size="xs">VAD {(r.vad * 100).toFixed(0)} %</Text>
              <Progress value={r.vad * 100} color="green" />
            </Stack>
            <Stack gap={2}>
              <Text size="xs">Wakeword {(r.wake_score * 100).toFixed(0)} %</Text>
              <Progress value={r.wake_score * 100} color="grape" />
            </Stack>
          </Group>
          <Table fz="xs">
            <Table.Tbody>
              <Table.Tr>
                <Table.Td>Gate-Latenz (Ausgabe → Mikrofon)</Table.Td>
                <Table.Td>{r.latency_s.toFixed(2)} s</Table.Td>
              </Table.Tr>
              <Table.Tr>
                <Table.Td>Gemessene Echo-Verzögerung</Table.Td>
                <Table.Td>
                  {r.delay_estimate_s !== null ? `${r.delay_estimate_s.toFixed(2)} s` : "–"} (Konfidenz {r.delay_confidence.toFixed(0)})
                </Table.Td>
              </Table.Tr>
              <Table.Tr>
                <Table.Td>Echodämpfung (ERLE)</Table.Td>
                <Table.Td>{r.erle_db !== null ? `${r.erle_db.toFixed(1)} dB` : "–"}</Table.Td>
              </Table.Tr>
              <Table.Tr>
                <Table.Td>Duplex-Begründung</Table.Td>
                <Table.Td>{r.duplex_reason}</Table.Td>
              </Table.Tr>
              <Table.Tr>
                <Table.Td>Gesperrte Frames / unterdrückte Wakewords</Table.Td>
                <Table.Td>
                  {r.gated_frames} / {r.suppressed_wakes}
                </Table.Td>
              </Table.Tr>
              <Table.Tr>
                <Table.Td>Verarbeitungszeit</Table.Td>
                <Table.Td>{r.processing_ms.toFixed(2)} ms pro Block</Table.Td>
              </Table.Tr>
            </Table.Tbody>
          </Table>
          {isAdmin && (
            <Group>
              <NumberInput size="xs" w={90} min={1} max={30} value={seconds} onChange={(v) => setSeconds(Number(v))} suffix=" s" />
              <Button size="xs" variant="light" leftSection={<IconDownload size={14} />} loading={recording} onClick={record}>
                Diagnoseaufnahme
              </Button>
              <Text size="xs" c="dimmed">
                nur auf ausdrückliche Anforderung, wird nicht gespeichert
              </Text>
            </Group>
          )}
        </Stack>
      ) : (
        <Text c="dimmed">Kein Audio aktiv (Mikrofon offline oder Endpoint inaktiv).</Text>
      )}
    </Card>
  );
}

export function AudioPage() {
  const endpoints = useQuery({ queryKey: ["endpoints"], queryFn: () => api.get<Endpoint[]>("/api/endpoints"), refetchInterval: 10000 });
  const devices = useQuery({ queryKey: ["devices"], queryFn: () => api.get<Device[]>("/api/devices") });
  const eps = useTelemetry<EndpointRuntime>("audio.endpoint.");
  const mics = useTelemetry<MicTelemetry>("audio.mic.");
  const speakers = useTelemetry<SpeakerTelemetry>("audio.speaker.");
  const events = useLiveEvents(40, (e) => e.type.startsWith("audio.") || e.type === "conversation.barge_in");
  const name = (id: string) => devices.data?.find((d) => d.id === id)?.name ?? id;

  return (
    <Stack>
      <PageHeader title="Audio" description="Live-Diagnose: Pegel, Sprachaktivität, Wakeword, Echo-Sperre und Audioausgabe" />
      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        {endpoints.data?.map((ep) => <EndpointCard key={ep.id} ep={ep} rt={eps[ep.id]} />)}
      </SimpleGrid>
      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        <Card withBorder>
          <Title order={5} mb="xs">
            Mikrofone
          </Title>
          <Table fz="xs">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Gerät</Table.Th>
                <Table.Th>Pegel</Table.Th>
                <Table.Th>Blöcke</Table.Th>
                <Table.Th>Überläufe</Table.Th>
                <Table.Th>Letzte Daten</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {Object.entries(mics).map(([id, m]) => (
                <Table.Tr key={id}>
                  <Table.Td>{name(id)}</Table.Td>
                  <Table.Td>{m.level_db.toFixed(1)} dBFS</Table.Td>
                  <Table.Td>{m.chunks}</Table.Td>
                  <Table.Td>{m.overruns}</Table.Td>
                  <Table.Td>{m.stale_s !== null ? `vor ${m.stale_s.toFixed(1)} s` : "–"}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Card>
        <Card withBorder>
          <Title order={5} mb="xs">
            Lautsprecher
          </Title>
          <Table fz="xs">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Gerät</Table.Th>
                <Table.Th>Status</Table.Th>
                <Table.Th>Latenz</Table.Th>
                <Table.Th>Talkback</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {Object.entries(speakers).map(([id, s]) => (
                <Table.Tr key={id}>
                  <Table.Td>{name(id)}</Table.Td>
                  <Table.Td>{s.playing ? <Badge color="violet">spielt</Badge> : "bereit"}</Table.Td>
                  <Table.Td>{s.latency_s.toFixed(1)} s</Table.Td>
                  <Table.Td>
                    {s.talkback
                      ? `${s.talkback.connected ? "verbunden" : "getrennt"}, ${(s.talkback.bytes_pulled / 32000).toFixed(0)} s, ${s.talkback.dropped_frames} verworfen`
                      : "–"}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Card>
      </SimpleGrid>
      <Card withBorder>
        <Title order={5} mb="xs">
          Audio-Ereignisse
        </Title>
        {events.map((e) => (
          <Text key={e.id} size="xs" ff="monospace">
            {fmtTime(e.timestamp)} {e.type} {JSON.stringify(e.payload)}
          </Text>
        ))}
      </Card>
    </Stack>
  );
}
