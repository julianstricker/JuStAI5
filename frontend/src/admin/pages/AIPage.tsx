import {
  ActionIcon,
  Autocomplete,
  Badge,
  Button,
  Card,
  Group,
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
  Textarea,
  Title,
} from "@mantine/core";
import { IconArrowDown, IconArrowUp, IconPlus, IconTrash } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "@/shared/api";

import { useIsAdmin } from "../auth";
import { PageHeader, useAction } from "../components/common";

interface ModelRef {
  provider: string;
  model: string;
  options: Record<string, unknown>;
}
interface RoleConfig {
  chain: ModelRef[];
  locality: "local_only" | "prefer_local" | "any";
  timeout_s: number;
}
interface AISettings {
  assistant_name: string;
  default_language: string;
  languages: string[];
  conversation_mode: "realtime" | "pipeline";
  system_prompt: string;
  roles: Record<string, RoleConfig>;
  voices: Record<string, string>;
  privacy: {
    cloud_allowed: boolean;
    camera_images_to_cloud: boolean;
    conversation_audio_to_cloud: boolean;
    personal_memories_to_cloud: boolean;
    announce_cloud_fallback: boolean;
  };
  cost_limits: { daily_usd: number | null; monthly_usd: number | null };
}
interface ProviderEntry {
  kind: string;
  id: string;
  plugin_id: string;
  locality: string;
}

const ROLES: { role: string; kind: string; label: string }[] = [
  { role: "realtime", kind: "realtime", label: "Realtime (Sprache ↔ Sprache)" },
  { role: "conversation", kind: "llm", label: "Gespräch (Pipeline)" },
  { role: "reasoning", kind: "llm", label: "Komplexes Reasoning" },
  { role: "vision", kind: "llm", label: "Bildanalyse" },
  { role: "memory", kind: "llm", label: "Gedächtnis-Extraktion" },
  { role: "tool_generation", kind: "llm", label: "Tool-Entwicklung" },
  { role: "background", kind: "llm", label: "Hintergrundaufgaben" },
  { role: "stt", kind: "stt", label: "Spracherkennung (STT)" },
  { role: "tts", kind: "tts", label: "Sprachausgabe (TTS)" },
  { role: "embedding", kind: "embedding", label: "Embeddings" },
];

function ModelSelect({ kind, provider, value, onChange }: { kind: string; provider: string; value: string; onChange: (v: string) => void }) {
  const models = useQuery({
    queryKey: ["models", kind, provider],
    queryFn: () => api.get<{ id: string }[]>(`/api/ai/providers/${kind}/${encodeURIComponent(provider)}/models`),
    enabled: !!provider && kind !== "tts",
    staleTime: 300_000,
  });
  const options = Array.from(new Set((models.data ?? []).map((m) => m.id)));
  return (
    <Autocomplete
      size="xs"
      placeholder="Modell-ID"
      data={options}
      value={value}
      onChange={onChange}
      w={260}
      limit={50}
    />
  );
}

function RoleEditor({ kind, label, cfg, providers, onChange }: { kind: string; label: string; cfg: RoleConfig; providers: ProviderEntry[]; onChange: (c: RoleConfig) => void }) {
  const options = providers.filter((p) => p.kind === kind).map((p) => ({ value: p.id, label: `${p.id} (${p.locality})` }));
  const setRef = (i: number, ref: Partial<ModelRef>) => onChange({ ...cfg, chain: cfg.chain.map((r, j) => (j === i ? { ...r, ...ref } : r)) });
  const move = (i: number, d: number) => {
    const chain = [...cfg.chain];
    const [x] = chain.splice(i, 1);
    chain.splice(i + d, 0, x);
    onChange({ ...cfg, chain });
  };
  return (
    <Card withBorder>
      <Group justify="space-between" mb="xs">
        <Text fw={600}>{label}</Text>
        <Group gap="xs">
          <Select
            size="xs"
            w={190}
            value={cfg.locality}
            onChange={(v) => onChange({ ...cfg, locality: (v ?? "any") as RoleConfig["locality"] })}
            data={[
              { value: "any", label: "lokal oder Cloud" },
              { value: "prefer_local", label: "lokal bevorzugt" },
              { value: "local_only", label: "nur lokal" },
            ]}
          />
          <NumberInput size="xs" w={90} value={cfg.timeout_s} suffix=" s" onChange={(v) => onChange({ ...cfg, timeout_s: Number(v) })} />
        </Group>
      </Group>
      <Stack gap="xs">
        {cfg.chain.map((ref, i) => (
          <Group key={i} gap="xs">
            <Badge variant="light">{i === 0 ? "primär" : `Fallback ${i}`}</Badge>
            <Select size="xs" w={200} data={options} value={ref.provider} onChange={(v) => setRef(i, { provider: v ?? "" })} />
            {kind !== "tts" && kind !== "embedding" ? (
              <ModelSelect kind={kind} provider={ref.provider} value={ref.model} onChange={(model) => setRef(i, { model })} />
            ) : (
              <TextInput size="xs" w={260} placeholder="Modell (optional)" value={ref.model} onChange={(e) => setRef(i, { model: e.currentTarget.value })} />
            )}
            <ActionIcon size="sm" variant="subtle" disabled={i === 0} onClick={() => move(i, -1)}>
              <IconArrowUp size={14} />
            </ActionIcon>
            <ActionIcon size="sm" variant="subtle" disabled={i === cfg.chain.length - 1} onClick={() => move(i, 1)}>
              <IconArrowDown size={14} />
            </ActionIcon>
            <ActionIcon size="sm" variant="subtle" color="red" onClick={() => onChange({ ...cfg, chain: cfg.chain.filter((_, j) => j !== i) })}>
              <IconTrash size={14} />
            </ActionIcon>
          </Group>
        ))}
        <Button size="xs" variant="subtle" leftSection={<IconPlus size={14} />} onClick={() => onChange({ ...cfg, chain: [...cfg.chain, { provider: options[0]?.value ?? "", model: "", options: {} }] })}>
          Provider hinzufügen
        </Button>
      </Stack>
    </Card>
  );
}

interface UsageRow {
  day: string;
  provider: string;
  model: string;
  role: string;
  requests: number;
  failures: number;
  input_tokens: number;
  output_tokens: number;
  audio_seconds: number;
  cost_usd: number;
  avg_latency_ms: number;
}

export function AIPage() {
  const isAdmin = useIsAdmin();
  const settings = useQuery({ queryKey: ["ai-settings"], queryFn: () => api.get<AISettings>("/api/ai/settings") });
  const providers = useQuery({ queryKey: ["ai-providers"], queryFn: () => api.get<ProviderEntry[]>("/api/ai/providers") });
  const usage = useQuery({ queryKey: ["ai-usage"], queryFn: () => api.get<UsageRow[]>("/api/ai/usage"), enabled: isAdmin });
  const voices = useQuery({
    queryKey: ["voices"],
    queryFn: () => api.get<{ id: string; language: string }[]>("/api/ai/providers/tts/piper/models"),
  });
  const [draft, setDraft] = useState<AISettings | null>(null);
  useEffect(() => {
    if (settings.data) setDraft(settings.data);
  }, [settings.data]);
  const save = useAction((s: AISettings) => api.put("/api/ai/settings", s), { invalidate: [["ai-settings"], ["ai-status"]], success: "KI-Einstellungen gespeichert" });
  if (!draft) return null;
  const role = (r: string): RoleConfig => draft.roles[r] ?? { chain: [], locality: "any", timeout_s: 60 };
  const privacy = (k: keyof AISettings["privacy"], label: string) => (
    <Switch label={label} checked={draft.privacy[k]} onChange={(e) => setDraft({ ...draft, privacy: { ...draft.privacy, [k]: e.currentTarget.checked } })} />
  );

  return (
    <Stack>
      <PageHeader
        title="KI-Provider"
        description="Welche Modelle welche Aufgaben übernehmen, Fallbacks, Stimmen und Datenschutzregeln"
        actions={
          isAdmin && (
            <Button onClick={() => save.mutate(draft)} loading={save.isPending}>
              Speichern
            </Button>
          )
        }
      />
      <Tabs defaultValue="general">
        <Tabs.List>
          <Tabs.Tab value="general">Allgemein</Tabs.Tab>
          <Tabs.Tab value="models">Modelle & Fallbacks</Tabs.Tab>
          <Tabs.Tab value="privacy">Datenschutz & Kosten</Tabs.Tab>
          <Tabs.Tab value="usage">Nutzung</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="general" pt="md">
          <Card withBorder>
            <Stack>
              <Group grow>
                <TextInput label="Name des Assistenten" value={draft.assistant_name} onChange={(e) => setDraft({ ...draft, assistant_name: e.currentTarget.value })} />
                <Select
                  label="Gesprächsmodus"
                  data={[
                    { value: "realtime", label: "Realtime (natives Sprachmodell)" },
                    { value: "pipeline", label: "Pipeline (STT → LLM → TTS)" },
                  ]}
                  value={draft.conversation_mode}
                  onChange={(v) => setDraft({ ...draft, conversation_mode: (v ?? "pipeline") as AISettings["conversation_mode"] })}
                />
              </Group>
              <Group grow>
                <Select label="Standardsprache" data={["de", "it", "en"]} value={draft.default_language} onChange={(v) => setDraft({ ...draft, default_language: v ?? "de" })} />
                <MultiSelect label="Sprachen" data={["de", "it", "en"]} value={draft.languages} onChange={(v) => setDraft({ ...draft, languages: v })} />
              </Group>
              <Title order={6}>Stimmen (Pipeline-TTS)</Title>
              <Group grow>
                {draft.languages.map((lang) => (
                  <Select
                    key={lang}
                    label={lang}
                    data={(voices.data ?? []).map((v) => v.id)}
                    value={draft.voices[lang] ?? null}
                    onChange={(v) => setDraft({ ...draft, voices: { ...draft.voices, [lang]: v ?? "" } })}
                  />
                ))}
              </Group>
              <Textarea
                label="Zusätzlicher Systemprompt"
                autosize
                minRows={4}
                value={draft.system_prompt}
                onChange={(e) => setDraft({ ...draft, system_prompt: e.currentTarget.value })}
              />
            </Stack>
          </Card>
        </Tabs.Panel>
        <Tabs.Panel value="models" pt="md">
          <Stack>
            {ROLES.map(({ role: r, kind, label }) => (
              <RoleEditor key={r} kind={kind} label={label} cfg={role(r)} providers={providers.data ?? []} onChange={(c) => setDraft({ ...draft, roles: { ...draft.roles, [r]: c } })} />
            ))}
          </Stack>
        </Tabs.Panel>
        <Tabs.Panel value="privacy" pt="md">
          <SimpleGrid cols={{ base: 1, md: 2 }}>
            <Card withBorder>
              <Stack>
                <Title order={5}>Datenschutz</Title>
                {privacy("cloud_allowed", "Cloud-KI generell erlaubt")}
                {privacy("conversation_audio_to_cloud", "Gesprächsaudio an Cloud-Modelle")}
                {privacy("camera_images_to_cloud", "Kamerabilder an Cloud-Modelle")}
                {privacy("personal_memories_to_cloud", "Persönliche Erinnerungen an Cloud-Modelle")}
                {privacy("announce_cloud_fallback", "Wechsel von lokal zu Cloud protokollieren")}
                <Text size="xs" c="dimmed">
                  Bei „nur lokal“ wird für eine Aufgabe niemals ein Cloud-Provider verwendet – auch nicht als Fallback.
                </Text>
              </Stack>
            </Card>
            <Card withBorder>
              <Stack>
                <Title order={5}>Kostenlimit</Title>
                <NumberInput
                  label="Tageslimit (USD)"
                  description="Danach werden Cloud-Provider übersprungen"
                  value={draft.cost_limits.daily_usd ?? ""}
                  decimalScale={2}
                  onChange={(v) => setDraft({ ...draft, cost_limits: { ...draft.cost_limits, daily_usd: typeof v === "number" ? v : null } })}
                />
              </Stack>
            </Card>
          </SimpleGrid>
        </Tabs.Panel>
        <Tabs.Panel value="usage" pt="md">
          <Table striped fz="sm">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Tag</Table.Th>
                <Table.Th>Provider / Modell</Table.Th>
                <Table.Th>Rolle</Table.Th>
                <Table.Th>Anfragen</Table.Th>
                <Table.Th>Fehler</Table.Th>
                <Table.Th>Tokens ein/aus</Table.Th>
                <Table.Th>Audio</Table.Th>
                <Table.Th>Ø Latenz</Table.Th>
                <Table.Th>Kosten</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {usage.data?.map((u, i) => (
                <Table.Tr key={i}>
                  <Table.Td>{u.day.slice(0, 10)}</Table.Td>
                  <Table.Td>
                    {u.provider} {u.model}
                  </Table.Td>
                  <Table.Td>{u.role}</Table.Td>
                  <Table.Td>{u.requests}</Table.Td>
                  <Table.Td>{u.failures}</Table.Td>
                  <Table.Td>
                    {u.input_tokens}/{u.output_tokens}
                  </Table.Td>
                  <Table.Td>{u.audio_seconds} s</Table.Td>
                  <Table.Td>{u.avg_latency_ms} ms</Table.Td>
                  <Table.Td>{u.cost_usd.toFixed(4)} $</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
