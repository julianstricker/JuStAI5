import {
  ActionIcon,
  Badge,
  Button,
  Card,
  FileButton,
  Checkbox,
  Divider,
  Group,
  Modal,
  MultiSelect,
  NumberInput,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Tabs,
  Text,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { IconEdit, IconMicrophone, IconPlus, IconTrash, IconWaveSine } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/shared/api";
import type { Device, DeviceRole, Endpoint, EndpointConfig, Room, RoomPolicy } from "@/shared/types";

import { useIsAdmin } from "../auth";
import { PageHeader, StatusBadge, notifyError, notifyOk, useAction } from "../components/common";

const ROLE_LABEL: Record<DeviceRole, string> = { mic: "Mikrofon", camera: "Kamera", speaker: "Lautsprecher", display: "Display" };
const ROLE_CAP: Record<DeviceRole, string> = { mic: "audio.input", camera: "video.input", speaker: "audio.output", display: "display.text" };

const DEFAULT_CONFIG: EndpointConfig = {
  wakeword: { enabled: true, models: ["hey_jarvis"], threshold: 0.5, threshold_during_playback: 0.85 },
  audio: {
    duplex: "auto",
    aec: true,
    noise_suppression: true,
    output_latency_ms: null,
    echo_tail_ms: 600,
    input_gain_db: 0,
    vad_threshold: 0.5,
    barge_in: true,
    barge_in_min_speech_ms: 300,
  },
  conversation: {
    mode: "default",
    inactivity_timeout_s: 10,
    end_of_utterance_silence_ms: 700,
    max_utterance_s: 30,
    voice: null,
    default_role: "resident",
    follow_up_listening: true,
    send_video: false,
  },
};

function RoomModal({ room, onClose }: { room: Room | null; onClose: () => void }) {
  const [name, setName] = useState(room?.name ?? "");
  const [description, setDescription] = useState(room?.description ?? "");
  const [floor, setFloor] = useState(room?.floor ?? "");
  const [policy, setPolicy] = useState<RoomPolicy>({
    shared_space: true,
    vision_allowed: true,
    face_recognition_allowed: true,
    cloud_media_allowed: true,
    announcements_allowed: true,
    ...room?.policy,
  });
  const save = useAction(
    () => {
      const body = { name, description, floor: floor || null, policy };
      return room ? api.patch(`/api/rooms/${room.id}`, body) : api.post("/api/rooms", body);
    },
    { invalidate: [["rooms"]], success: "Raum gespeichert" },
  );
  const toggle = (k: keyof RoomPolicy, label: string, hint: string) => (
    <Switch label={label} description={hint} checked={Boolean(policy[k])} onChange={(e) => setPolicy({ ...policy, [k]: e.currentTarget.checked })} />
  );
  return (
    <Modal opened onClose={onClose} title={room ? `Raum ${room.name}` : "Neuer Raum"}>
      <Stack>
        <TextInput label="Name" value={name} onChange={(e) => setName(e.currentTarget.value)} required />
        <TextInput label="Beschreibung" value={description} onChange={(e) => setDescription(e.currentTarget.value)} />
        <TextInput label="Etage" value={floor} onChange={(e) => setFloor(e.currentTarget.value)} />
        <Divider label="Richtlinien" />
        {toggle("shared_space", "Gemeinschaftsraum", "Private Inhalte werden hier nicht auf Displays gezeigt")}
        {toggle("vision_allowed", "Bildanalyse erlaubt", "Kameras dieses Raums dürfen analysiert werden")}
        {toggle("face_recognition_allowed", "Gesichtserkennung erlaubt", "")}
        {toggle("cloud_media_allowed", "Bilder/Audio an Cloud-KI", "Kamerabilder dieses Raums dürfen an Cloud-Modelle")}
        {toggle("announcements_allowed", "Durchsagen erlaubt", "Andere Räume dürfen hier ausdrücklich Durchsagen machen")}
        <Button
          onClick={async () => {
            await save.mutateAsync(undefined);
            onClose();
          }}
          loading={save.isPending}
          disabled={!name}
        >
          Speichern
        </Button>
      </Stack>
    </Modal>
  );
}

function EndpointModal({
  room,
  endpoint,
  devices,
  onClose,
}: {
  room: Room;
  endpoint: Endpoint | null;
  devices: Device[];
  onClose: () => void;
}) {
  const [name, setName] = useState(endpoint?.name ?? `${room.name}`);
  const [config, setConfig] = useState<EndpointConfig>(endpoint?.config ?? DEFAULT_CONFIG);
  const [refs, setRefs] = useState(endpoint?.devices ?? []);
  const [language, setLanguage] = useState<string | null>(endpoint?.language ?? null);
  const [group, setGroup] = useState(endpoint?.arbitration_group ?? "default");
  const [priority, setPriority] = useState(endpoint?.priority ?? 0);
  const [enabled, setEnabled] = useState(endpoint?.enabled ?? true);
  const roomDevices = devices.filter((d) => d.room_id === room.id || d.room_id === null);
  const models = useQuery({
    queryKey: ["wakeword-models"],
    queryFn: () => api.get<{ id: string; name: string; phrase: string }[]>("/api/ai/providers/wakeword/openwakeword/models"),
  });

  const pick = (role: DeviceRole) => refs.find((r) => r.role === role)?.device_id ?? null;
  const setRole = (role: DeviceRole, id: string | null) =>
    setRefs([...refs.filter((r) => r.role !== role), ...(id ? [{ device_id: id, role, priority: 0 }] : [])]);
  const upd = <K extends keyof EndpointConfig>(k: K, v: Partial<EndpointConfig[K]>) => setConfig({ ...config, [k]: { ...config[k], ...v } });

  const save = useAction(
    () => {
      const body = { name, room_id: room.id, devices: refs, config, language, arbitration_group: group, priority, enabled };
      return endpoint ? api.patch(`/api/endpoints/${endpoint.id}`, body) : api.post("/api/endpoints", body);
    },
    { invalidate: [["endpoints"], ["rooms"]], success: "Endpunkt gespeichert" },
  );

  return (
    <Modal opened onClose={onClose} title={endpoint ? `Interaction Endpoint ${endpoint.name}` : "Neuer Interaction Endpoint"} size="lg">
      <Stack>
        <Group grow>
          <TextInput label="Name" value={name} onChange={(e) => setName(e.currentTarget.value)} />
          <Switch label="Aktiv" checked={enabled} onChange={(e) => setEnabled(e.currentTarget.checked)} mt="lg" />
        </Group>
        <SimpleGrid cols={2}>
          {(Object.keys(ROLE_LABEL) as DeviceRole[]).map((role) => (
            <Select
              key={role}
              label={ROLE_LABEL[role]}
              clearable
              value={pick(role)}
              onChange={(v) => setRole(role, v)}
              data={roomDevices
                .filter((d) => d.capabilities.includes(ROLE_CAP[role]) || d.status !== "online")
                .map((d) => ({ value: d.id, label: `${d.name}${d.capabilities.includes(ROLE_CAP[role]) ? "" : " (Fähigkeit unbekannt)"}` }))}
            />
          ))}
        </SimpleGrid>
        <Tabs defaultValue="wake">
          <Tabs.List>
            <Tabs.Tab value="wake">Wakeword</Tabs.Tab>
            <Tabs.Tab value="audio">Audio</Tabs.Tab>
            <Tabs.Tab value="conv">Gespräch</Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="wake" pt="sm">
            <Stack>
              <Switch label="Wakeword aktiv" checked={config.wakeword.enabled} onChange={(e) => upd("wakeword", { enabled: e.currentTarget.checked })} />
              <MultiSelect
                label="Wakeword-Modelle"
                data={(models.data ?? []).map((m) => ({ value: m.id, label: `${m.phrase} (${m.name})` }))}
                value={config.wakeword.models}
                onChange={(v) => upd("wakeword", { models: v })}
                description="Mehrere möglich. Eigene Modelle (openWakeWord, .onnx) lassen sich hochladen."
              />
              <Group gap="xs">
                <FileButton
                  accept=".onnx"
                  onChange={(f) => {
                    if (!f) return;
                    const form = new FormData();
                    form.append("file", f);
                    api
                      .upload<{ id: string }>("/api/ai/wakewords", form)
                      .then((r) => {
                        notifyOk(`Wakeword „${r.id}“ installiert`);
                        void models.refetch();
                        upd("wakeword", { models: [...new Set([...config.wakeword.models, r.id])] });
                      })
                      .catch(notifyError);
                  }}
                >
                  {(props) => (
                    <Button {...props} size="xs" variant="default">
                      Eigenes Wakeword hochladen (.onnx)
                    </Button>
                  )}
                </FileButton>
                <Text size="xs" c="dimmed">
                  Dateiname = ID, z. B. hey_justi.onnx
                </Text>
              </Group>
              <Group grow>
                <NumberInput label="Schwelle" step={0.05} min={0.05} max={0.99} decimalScale={2} value={config.wakeword.threshold} onChange={(v) => upd("wakeword", { threshold: Number(v) })} />
                <NumberInput
                  label="Schwelle während eigener Ausgabe"
                  description="nur Vollduplex"
                  step={0.05}
                  decimalScale={2}
                  value={config.wakeword.threshold_during_playback}
                  onChange={(v) => upd("wakeword", { threshold_during_playback: Number(v) })}
                />
              </Group>
              <Group grow>
                <TextInput label="Arbitrierungsgruppe" description="Mikrofone, die sich gegenseitig hören können" value={group} onChange={(e) => setGroup(e.currentTarget.value)} />
                <NumberInput label="Priorität" value={priority} onChange={(v) => setPriority(Number(v))} />
              </Group>
            </Stack>
          </Tabs.Panel>
          <Tabs.Panel value="audio" pt="sm">
            <Stack>
              <Select
                label="Duplex-Modus"
                data={[
                  { value: "auto", label: "Auto (sicher: halb, voll erst nach gemessener Echounterdrückung)" },
                  { value: "half", label: "Halbduplex (Eingabe während Ausgabe gesperrt)" },
                  { value: "full", label: "Vollduplex mit AEC und Barge-in" },
                ]}
                value={config.audio.duplex}
                onChange={(v) => upd("audio", { duplex: (v ?? "auto") as EndpointConfig["audio"]["duplex"] })}
              />
              <Group grow>
                <NumberInput
                  label="Ausgabelatenz (ms)"
                  description="leer = automatisch / Kalibrierung"
                  value={config.audio.output_latency_ms ?? ""}
                  onChange={(v) => upd("audio", { output_latency_ms: typeof v === "number" ? v : null })}
                />
                <NumberInput label="Echo-Nachlauf (ms)" value={config.audio.echo_tail_ms} onChange={(v) => upd("audio", { echo_tail_ms: Number(v) })} />
              </Group>
              <Group grow>
                <NumberInput label="Eingangsverstärkung (dB)" value={config.audio.input_gain_db} onChange={(v) => upd("audio", { input_gain_db: Number(v) })} />
                <NumberInput label="VAD-Schwelle" step={0.05} decimalScale={2} value={config.audio.vad_threshold} onChange={(v) => upd("audio", { vad_threshold: Number(v) })} />
              </Group>
              <Group>
                <Checkbox label="Echounterdrückung (AEC)" checked={config.audio.aec} onChange={(e) => upd("audio", { aec: e.currentTarget.checked })} />
                <Checkbox label="Rauschunterdrückung" checked={config.audio.noise_suppression} onChange={(e) => upd("audio", { noise_suppression: e.currentTarget.checked })} />
                <Checkbox label="Barge-in" checked={config.audio.barge_in} onChange={(e) => upd("audio", { barge_in: e.currentTarget.checked })} />
              </Group>
            </Stack>
          </Tabs.Panel>
          <Tabs.Panel value="conv" pt="sm">
            <Stack>
              <Select
                label="Modus"
                data={[
                  { value: "default", label: "Global (KI-Einstellungen)" },
                  { value: "realtime", label: "Realtime (natives Sprachmodell)" },
                  { value: "pipeline", label: "Pipeline (STT → LLM → TTS)" },
                ]}
                value={config.conversation.mode}
                onChange={(v) => upd("conversation", { mode: (v ?? "default") as EndpointConfig["conversation"]["mode"] })}
              />
              <Group grow>
                <NumberInput label="Inaktivitäts-Timeout (s)" min={3} value={config.conversation.inactivity_timeout_s} onChange={(v) => upd("conversation", { inactivity_timeout_s: Number(v) })} />
                <NumberInput label="Sprechpause bis Äußerungsende (ms)" value={config.conversation.end_of_utterance_silence_ms} onChange={(v) => upd("conversation", { end_of_utterance_silence_ms: Number(v) })} />
              </Group>
              <Group grow>
                <Select label="Sprache" clearable data={["de", "it", "en"]} value={language} onChange={setLanguage} />
                <Select
                  label="Rolle unbekannter Sprecher"
                  data={[
                    { value: "resident", label: "Bewohner" },
                    { value: "guest", label: "Gast" },
                  ]}
                  value={config.conversation.default_role}
                  onChange={(v) => upd("conversation", { default_role: v ?? "resident" })}
                />
              </Group>
            </Stack>
          </Tabs.Panel>
        </Tabs>
        <Button
          onClick={async () => {
            await save.mutateAsync(undefined);
            onClose();
          }}
          loading={save.isPending}
        >
          Speichern
        </Button>
      </Stack>
    </Modal>
  );
}

export function RoomsPage() {
  const isAdmin = useIsAdmin();
  const rooms = useQuery({ queryKey: ["rooms"], queryFn: () => api.get<Room[]>("/api/rooms") });
  const devices = useQuery({ queryKey: ["devices"], queryFn: () => api.get<Device[]>("/api/devices"), refetchInterval: 5000 });
  const endpoints = useQuery({ queryKey: ["endpoints"], queryFn: () => api.get<Endpoint[]>("/api/endpoints"), refetchInterval: 3000 });
  const [roomModal, setRoomModal] = useState<Room | null | "new">(null);
  const [epModal, setEpModal] = useState<{ room: Room; endpoint: Endpoint | null } | null>(null);

  const delRoom = useAction((id: string) => api.del(`/api/rooms/${id}`), { invalidate: [["rooms"]], success: "Raum gelöscht" });
  const delEp = useAction((id: string) => api.del(`/api/endpoints/${id}`), { invalidate: [["endpoints"]], success: "Endpunkt gelöscht" });
  const assign = useAction(({ id, room }: { id: string; room: string | null }) => api.patch(`/api/devices/${id}`, { room_id: room }), {
    invalidate: [["devices"], ["rooms"]],
  });
  const calibrate = useAction((id: string) => api.post<{ delay_s: number | null; interpretation?: string }>(`/api/endpoints/${id}/calibrate`), {
    invalidate: [["endpoints"]],
    success: (r) => (r.delay_s !== null ? `Echo-Verzögerung: ${r.delay_s.toFixed(2)} s` : (r.interpretation ?? "Keine Messung möglich")),
  });
  const startSession = useAction((id: string) => api.post(`/api/endpoints/${id}/start-session`), { success: "Gespräch gestartet" });

  const unassigned = devices.data?.filter((d) => !d.room_id) ?? [];

  return (
    <Stack>
      <PageHeader
        title="Räume"
        description="Räume gruppieren Geräte. Interaction Endpoints kombinieren Mikrofon, Kamera, Lautsprecher und Display eines Raums zu einem Kommunikationspunkt."
        actions={
          isAdmin && (
            <Button leftSection={<IconPlus size={16} />} onClick={() => setRoomModal("new")}>
              Raum
            </Button>
          )
        }
      />
      <SimpleGrid cols={{ base: 1, md: 2 }}>
        {rooms.data?.map((room) => {
          const roomDevices = devices.data?.filter((d) => d.room_id === room.id) ?? [];
          const roomEps = endpoints.data?.filter((e) => e.room_id === room.id) ?? [];
          return (
            <Card withBorder key={room.id}>
              <Group justify="space-between" mb="xs">
                <Title order={4}>{room.name}</Title>
                {isAdmin && (
                  <Group gap={4}>
                    <ActionIcon variant="subtle" onClick={() => setRoomModal(room)}>
                      <IconEdit size={16} />
                    </ActionIcon>
                    <ActionIcon variant="subtle" color="red" onClick={() => confirm(`Raum ${room.name} löschen?`) && delRoom.mutate(room.id)}>
                      <IconTrash size={16} />
                    </ActionIcon>
                  </Group>
                )}
              </Group>
              <Text size="sm" c="dimmed" mb="xs">
                {room.description}
              </Text>
              <Text fw={600} size="sm">
                Geräte
              </Text>
              <Stack gap={4} mb="sm">
                {roomDevices.map((d) => (
                  <Group key={d.id} justify="space-between">
                    <Group gap={6}>
                      <StatusBadge status={d.status} />
                      <Text size="sm">{d.name}</Text>
                    </Group>
                    <Group gap={4}>
                      {d.capabilities.slice(0, 5).map((c) => (
                        <Badge key={c} size="xs" variant="outline">
                          {c}
                        </Badge>
                      ))}
                      {isAdmin && (
                        <Tooltip label="Aus Raum entfernen">
                          <ActionIcon size="sm" variant="subtle" onClick={() => assign.mutate({ id: d.id, room: null })}>
                            <IconTrash size={12} />
                          </ActionIcon>
                        </Tooltip>
                      )}
                    </Group>
                  </Group>
                ))}
                {isAdmin && unassigned.length > 0 && (
                  <Select
                    placeholder="Gerät zuordnen …"
                    size="xs"
                    data={unassigned.map((d) => ({ value: d.id, label: d.name }))}
                    value={null}
                    onChange={(v) => v && assign.mutate({ id: v, room: room.id })}
                  />
                )}
              </Stack>
              <Group justify="space-between">
                <Text fw={600} size="sm">
                  Interaction Endpoints
                </Text>
                {isAdmin && (
                  <Button size="xs" variant="light" leftSection={<IconPlus size={14} />} onClick={() => setEpModal({ room, endpoint: null })}>
                    Endpoint
                  </Button>
                )}
              </Group>
              <Stack gap="xs" mt="xs">
                {roomEps.map((ep) => (
                  <Card key={ep.id} withBorder padding="xs">
                    <Group justify="space-between">
                      <Group gap={6}>
                        <IconMicrophone size={16} />
                        <Text size="sm" fw={600}>
                          {ep.name}
                        </Text>
                        {ep.session && <StatusBadge status={ep.session.state} />}
                        {!ep.enabled && <Badge color="gray">inaktiv</Badge>}
                        {ep.devices.length === 0 && (
                          <Tooltip label="Die Geräte dieses Endpoints wurden gelöscht. Neue Geräte zuordnen oder den Endpoint löschen.">
                            <Badge color="orange">keine Geräte</Badge>
                          </Tooltip>
                        )}
                      </Group>
                      {isAdmin && (
                        <Group gap={4}>
                          <Tooltip label="Echo-Latenz kalibrieren (spielt kurze Töne)">
                            <ActionIcon variant="subtle" loading={calibrate.isPending} onClick={() => calibrate.mutate(ep.id)}>
                              <IconWaveSine size={16} />
                            </ActionIcon>
                          </Tooltip>
                          <Button size="compact-xs" variant="subtle" onClick={() => startSession.mutate(ep.id)}>
                            Gespräch starten
                          </Button>
                          <ActionIcon variant="subtle" onClick={() => setEpModal({ room, endpoint: ep })}>
                            <IconEdit size={16} />
                          </ActionIcon>
                          <ActionIcon variant="subtle" color="red" onClick={() => confirm("Endpoint löschen?") && delEp.mutate(ep.id)}>
                            <IconTrash size={16} />
                          </ActionIcon>
                        </Group>
                      )}
                    </Group>
                    <Group gap={4} mt={4}>
                      {ep.devices.map((r) => (
                        <Badge key={r.role + r.device_id} size="xs" variant="light">
                          {ROLE_LABEL[r.role]}: {devices.data?.find((d) => d.id === r.device_id)?.name ?? r.device_id}
                        </Badge>
                      ))}
                    </Group>
                    {ep.runtime && (
                      <Text size="xs" c="dimmed" mt={4}>
                        {ep.runtime.duplex === "half" ? "Halbduplex" : "Vollduplex"} ({ep.runtime.duplex_reason}) · Gate-Latenz{" "}
                        {ep.runtime.latency_s.toFixed(2)} s · Pegel {ep.runtime.level_db.toFixed(0)} dBFS
                      </Text>
                    )}
                  </Card>
                ))}
                {!roomEps.length && (
                  <Text size="xs" c="dimmed">
                    Noch kein Endpoint – ohne Endpoint kann in diesem Raum nicht gesprochen werden.
                  </Text>
                )}
              </Stack>
            </Card>
          );
        })}
      </SimpleGrid>
      {roomModal && <RoomModal room={roomModal === "new" ? null : roomModal} onClose={() => setRoomModal(null)} />}
      {epModal && <EndpointModal room={epModal.room} endpoint={epModal.endpoint} devices={devices.data ?? []} onClose={() => setEpModal(null)} />}
    </Stack>
  );
}
