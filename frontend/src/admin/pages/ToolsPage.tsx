import { Accordion, Alert, Badge, Button, Card, Code, Group, Stack, Table, Tabs, Text, Textarea, Title } from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/shared/api";
import type { ToolInfo } from "@/shared/types";

import { PageHeader, StatusBadge, fmtTime, useAction } from "../components/common";

interface Version {
  id: string;
  version: number;
  status: string;
  spec: Record<string, unknown>;
  manifest: Record<string, unknown>;
  code: string;
  tests: string;
  validation: {
    static?: { ok: boolean; issues: string[] };
    tests?: { ok: boolean; output: string };
    review?: { ok: boolean; findings: string[] };
  };
  created_at: string;
  approved_by: string | null;
}
interface Project {
  id: string;
  plugin_id: string;
  title: string;
  request: string;
  status: string;
  active_version: number | null;
  created_at: string;
  versions: Version[];
}

function Check({ label, ok, children }: { label: string; ok: boolean | undefined; children?: React.ReactNode }) {
  return (
    <Stack gap={2}>
      <Group gap="xs">
        <Badge color={ok === undefined ? "gray" : ok ? "green" : "red"}>{ok === undefined ? "–" : ok ? "OK" : "fehlgeschlagen"}</Badge>
        <Text size="sm" fw={600}>
          {label}
        </Text>
      </Group>
      {children}
    </Stack>
  );
}

function ProjectCard({ project }: { project: Project }) {
  const approve = useAction((v: number) => api.post(`/api/devtools/projects/${project.id}/versions/${v}/approve`), {
    invalidate: [["devtools"], ["tools"], ["plugins"]],
    success: "Version freigegeben und aktiviert",
  });
  const rollback = useAction((v: number) => api.post(`/api/devtools/projects/${project.id}/rollback`, { version: v }), {
    invalidate: [["devtools"], ["tools"]],
    success: "Rollback durchgeführt",
  });
  const deactivate = useAction(() => api.post(`/api/devtools/projects/${project.id}/deactivate`), { invalidate: [["devtools"], ["tools"]], success: "Deaktiviert" });
  const remove = useAction(() => api.del(`/api/devtools/projects/${project.id}`), { invalidate: [["devtools"], ["tools"], ["plugins"]], success: "Gelöscht" });
  const revise = useAction((feedback: string) => api.post(`/api/devtools/projects/${project.id}/revise`, { feedback }), {
    invalidate: [["devtools"]],
    success: "Neue Version wird erstellt",
  });
  const [feedback, setFeedback] = useState("");
  return (
    <Card withBorder>
      <Group justify="space-between">
        <Group gap="xs">
          <Title order={5}>{project.title}</Title>
          <StatusBadge status={project.status} />
          {project.active_version && <Badge color="green">aktiv: v{project.active_version}</Badge>}
        </Group>
        <Group gap="xs">
          {project.active_version && (
            <Button size="xs" variant="subtle" color="red" onClick={() => deactivate.mutate(undefined)}>
              Deaktivieren
            </Button>
          )}
          <Button
            size="xs"
            variant="subtle"
            color="red"
            onClick={() => confirm(`Projekt „${project.title}“ mit allen Versionen und dem erzeugten Plugin löschen?`) && remove.mutate(undefined)}
          >
            Löschen
          </Button>
        </Group>
      </Group>
      <Text size="sm" c="dimmed">
        „{project.request}“ · Plugin {project.plugin_id} · {fmtTime(project.created_at)}
      </Text>
      <Accordion mt="sm">
        {project.versions.map((v) => (
          <Accordion.Item key={v.id} value={v.id}>
            <Accordion.Control>
              <Group gap="xs">
                <Text>v{v.version}</Text>
                <StatusBadge status={v.status} />
              </Group>
            </Accordion.Control>
            <Accordion.Panel>
              <Stack>
                <Check label="Statische Prüfung" ok={v.validation.static?.ok}>
                  {v.validation.static?.issues.map((i) => (
                    <Text key={i} size="xs">
                      • {i}
                    </Text>
                  ))}
                </Check>
                <Check label="Automatische Tests (Sandbox)" ok={v.validation.tests?.ok}>
                  {v.validation.tests?.output && <Code block>{v.validation.tests.output.slice(-3000)}</Code>}
                </Check>
                <Check label="Sicherheitsprüfung" ok={v.validation.review?.ok}>
                  {v.validation.review?.findings.map((f) => (
                    <Text key={f} size="xs">
                      • {f}
                    </Text>
                  ))}
                </Check>
                <Tabs defaultValue="code">
                  <Tabs.List>
                    <Tabs.Tab value="code">Code</Tabs.Tab>
                    <Tabs.Tab value="tests">Tests</Tabs.Tab>
                    <Tabs.Tab value="manifest">Manifest</Tabs.Tab>
                  </Tabs.List>
                  <Tabs.Panel value="code">
                    <Code block>{v.code}</Code>
                  </Tabs.Panel>
                  <Tabs.Panel value="tests">
                    <Code block>{v.tests}</Code>
                  </Tabs.Panel>
                  <Tabs.Panel value="manifest">
                    <Code block>{JSON.stringify(v.manifest, null, 2)}</Code>
                  </Tabs.Panel>
                </Tabs>
                <Group>
                  {v.status === "tested" && (
                    <Button onClick={() => approve.mutate(v.version)} loading={approve.isPending}>
                      Freigeben & aktivieren
                    </Button>
                  )}
                  {(v.status === "superseded" || v.status === "rolled_back") && (
                    <Button variant="light" onClick={() => rollback.mutate(v.version)}>
                      Auf diese Version zurück
                    </Button>
                  )}
                </Group>
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>
        ))}
      </Accordion>
      <Group mt="sm" align="flex-end">
        <Textarea style={{ flex: 1 }} placeholder="Änderungswunsch für eine neue Version …" value={feedback} onChange={(e) => setFeedback(e.currentTarget.value)} />
        <Button variant="light" disabled={!feedback} onClick={() => revise.mutate(feedback)}>
          Überarbeiten
        </Button>
      </Group>
    </Card>
  );
}

export function ToolsPage() {
  const tools = useQuery({ queryKey: ["tools"], queryFn: () => api.get<ToolInfo[]>("/api/tools") });
  const projects = useQuery({ queryKey: ["devtools"], queryFn: () => api.get<Project[]>("/api/devtools/projects"), refetchInterval: 5000 });
  const [request, setRequest] = useState("");
  const create = useAction(() => api.post("/api/devtools/projects", { request }), { invalidate: [["devtools"]], success: "Entwicklung gestartet" });
  return (
    <Stack>
      <PageHeader title="Tools" description="Alle Werkzeuge des Assistenten und selbst entwickelte Fähigkeiten (Sandbox, Tests, Freigabe, Rollback)" />
      <Tabs defaultValue="dev">
        <Tabs.List>
          <Tabs.Tab value="dev">Entwicklung</Tabs.Tab>
          <Tabs.Tab value="all">Alle Tools ({tools.data?.length ?? 0})</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="dev" pt="md">
          <Stack>
            <Card withBorder>
              <Stack>
                <Textarea
                  label="Neue Fähigkeit"
                  description="Beschreibe, was der Assistent können soll. Er prüft zuerst vorhandene Tools; sonst erzeugt er eine Spezifikation, Code und Tests und testet sie isoliert."
                  value={request}
                  onChange={(e) => setRequest(e.currentTarget.value)}
                  placeholder="z. B. Erkenne anhand der Garagenkamera, ob das Garagentor offen oder geschlossen ist."
                />
                <Button w={200} onClick={() => create.mutate(undefined)} disabled={!request} loading={create.isPending}>
                  Entwickeln
                </Button>
              </Stack>
            </Card>
            <Alert color="gray">KI-generierter Code läuft ausschließlich im isolierten Sandbox-Container und wird erst nach deiner Freigabe aktiviert.</Alert>
            {projects.data?.map((p) => <ProjectCard key={p.id} project={p} />)}
          </Stack>
        </Tabs.Panel>
        <Tabs.Panel value="all" pt="md">
          <Table striped>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Tool</Table.Th>
                <Table.Th>Beschreibung</Table.Th>
                <Table.Th>Herkunft</Table.Th>
                <Table.Th>Berechtigungen</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {tools.data?.map((t) => (
                <Table.Tr key={t.name}>
                  <Table.Td>
                    <Code>{t.name}</Code>
                    {t.requires_confirmation && (
                      <Badge size="xs" color="orange" ml={4}>
                        Bestätigung
                      </Badge>
                    )}
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{t.description}</Text>
                  </Table.Td>
                  <Table.Td>{t.owner}</Table.Td>
                  <Table.Td>{t.permissions.join(", ")}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
