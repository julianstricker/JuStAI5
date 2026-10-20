import {
  Accordion,
  Alert,
  Badge,
  Button,
  Card,
  Code,
  Group,
  Stack,
  Table,
  Tabs,
  Text,
  Textarea,
  Title,
} from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { useT } from "@/shared/i18n";

import { api } from "@/shared/api";
import type { ToolInfo } from "@/shared/types";

import {
  PageHeader,
  StatusBadge,
  fmtTime,
  useAction,
} from "../components/common";

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

function Check({
  label,
  ok,
  children,
}: {
  label: string;
  ok: boolean | undefined;
  children?: React.ReactNode;
}) {
  const t = useT();
  return (
    <Stack gap={2}>
      <Group gap="xs">
        <Badge color={ok === undefined ? "gray" : ok ? "green" : "red"}>
          {ok === undefined ? "–" : ok ? "OK" : t("tools.failed")}
        </Badge>
        <Text size="sm" fw={600}>
          {label}
        </Text>
      </Group>
      {children}
    </Stack>
  );
}

function ProjectCard({ project }: { project: Project }) {
  const t = useT();
  const approve = useAction(
    (v: number) =>
      api.post(`/api/devtools/projects/${project.id}/versions/${v}/approve`),
    {
      invalidate: [["devtools"], ["tools"], ["plugins"]],
      success: t("tools.approved"),
    },
  );
  const rollback = useAction(
    (v: number) =>
      api.post(`/api/devtools/projects/${project.id}/rollback`, { version: v }),
    {
      invalidate: [["devtools"], ["tools"]],
      success: t("tools.rolledBack"),
    },
  );
  const deactivate = useAction(
    () => api.post(`/api/devtools/projects/${project.id}/deactivate`),
    { invalidate: [["devtools"], ["tools"]], success: t("tools.deactivated") },
  );
  const remove = useAction(
    () => api.del(`/api/devtools/projects/${project.id}`),
    {
      invalidate: [["devtools"], ["tools"], ["plugins"]],
      success: t("tools.deleted"),
    },
  );
  const revise = useAction(
    (feedback: string) =>
      api.post(`/api/devtools/projects/${project.id}/revise`, { feedback }),
    {
      invalidate: [["devtools"]],
      success: t("tools.revising"),
    },
  );
  const [feedback, setFeedback] = useState("");
  return (
    <Card withBorder>
      <Group justify="space-between">
        <Group gap="xs">
          <Title order={5}>{project.title}</Title>
          <StatusBadge status={project.status} />
          {project.active_version && (
            <Badge color="green">
              {t("tools.active", { v: project.active_version })}
            </Badge>
          )}
        </Group>
        <Group gap="xs">
          {project.active_version && (
            <Button
              size="xs"
              variant="subtle"
              color="red"
              onClick={() => deactivate.mutate(undefined)}
            >
              {t("tools.deactivate")}
            </Button>
          )}
          <Button
            size="xs"
            variant="subtle"
            color="red"
            onClick={() =>
              confirm(t("tools.confirmDelete", { title: project.title })) &&
              remove.mutate(undefined)
            }
          >
            {t("common.delete")}
          </Button>
        </Group>
      </Group>
      <Text size="sm" c="dimmed">
        „{project.request}“ · Plugin {project.plugin_id} ·{" "}
        {fmtTime(project.created_at)}
      </Text>
      {project.status === "needs_config" && (
        <Alert color="orange" mt="xs">
          {t("tools.needsConfigHint", { plugin: project.plugin_id })}
        </Alert>
      )}
      {!!(project.versions[0]?.spec?.events as { type: string }[] | undefined)
        ?.length && (
        <Text size="xs" c="dimmed">
          {t("tools.events", {
            list: (project.versions[0].spec.events as { type: string }[])
              .map((e) => e.type)
              .join(", "),
          })}
        </Text>
      )}
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
                <Check label={t("tools.static")} ok={v.validation.static?.ok}>
                  {v.validation.static?.issues.map((i) => (
                    <Text key={i} size="xs">
                      • {i}
                    </Text>
                  ))}
                </Check>
                <Check label={t("tools.tests")} ok={v.validation.tests?.ok}>
                  {v.validation.tests?.output && (
                    <Code block>{v.validation.tests.output.slice(-3000)}</Code>
                  )}
                </Check>
                <Check label={t("tools.review")} ok={v.validation.review?.ok}>
                  {v.validation.review?.findings.map((f) => (
                    <Text key={f} size="xs">
                      • {f}
                    </Text>
                  ))}
                </Check>
                <Tabs defaultValue="code">
                  <Tabs.List>
                    <Tabs.Tab value="code">{t("tools.code")}</Tabs.Tab>
                    <Tabs.Tab value="tests">{t("tools.testsTab")}</Tabs.Tab>
                    <Tabs.Tab value="manifest">{t("tools.manifest")}</Tabs.Tab>
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
                    <Button
                      onClick={() => approve.mutate(v.version)}
                      loading={approve.isPending}
                    >
                      {t("tools.approve")}
                    </Button>
                  )}
                  {(v.status === "superseded" ||
                    v.status === "rolled_back") && (
                    <Button
                      variant="light"
                      onClick={() => rollback.mutate(v.version)}
                    >
                      {t("tools.rollbackTo")}
                    </Button>
                  )}
                </Group>
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>
        ))}
      </Accordion>
      <Group mt="sm" align="flex-end">
        <Textarea
          style={{ flex: 1 }}
          placeholder={t("tools.feedbackPlaceholder")}
          value={feedback}
          onChange={(e) => setFeedback(e.currentTarget.value)}
        />
        <Button
          variant="light"
          disabled={!feedback}
          onClick={() => revise.mutate(feedback)}
        >
          {t("tools.revise")}
        </Button>
      </Group>
    </Card>
  );
}

export function ToolsPage() {
  const tools = useQuery({
    queryKey: ["tools"],
    queryFn: () => api.get<ToolInfo[]>("/api/tools"),
  });
  const projects = useQuery({
    queryKey: ["devtools"],
    queryFn: () => api.get<Project[]>("/api/devtools/projects"),
    refetchInterval: 5000,
  });
  const [request, setRequest] = useState("");
  const t = useT();
  const create = useAction(
    () => api.post("/api/devtools/projects", { request }),
    { invalidate: [["devtools"]], success: t("tools.started") },
  );
  return (
    <Stack>
      <PageHeader title={t("nav.tools")} description={t("tools.desc")} />
      <Tabs defaultValue="dev">
        <Tabs.List>
          <Tabs.Tab value="dev">{t("tools.tabDev")}</Tabs.Tab>
          <Tabs.Tab value="all">
            {t("tools.tabAll", { n: tools.data?.length ?? 0 })}
          </Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="dev" pt="md">
          <Stack>
            <Card withBorder>
              <Stack>
                <Textarea
                  label={t("tools.newCapability")}
                  description={t("tools.newCapabilityHint2")}
                  value={request}
                  onChange={(e) => setRequest(e.currentTarget.value)}
                  placeholder={t("tools.placeholder")}
                />
                <Button
                  w={200}
                  onClick={() => create.mutate(undefined)}
                  disabled={!request}
                  loading={create.isPending}
                >
                  {t("tools.develop")}
                </Button>
              </Stack>
            </Card>
            <Alert color="gray">{t("tools.sandboxHint")}</Alert>
            {projects.data?.map((p) => (
              <ProjectCard key={p.id} project={p} />
            ))}
          </Stack>
        </Tabs.Panel>
        <Tabs.Panel value="all" pt="md">
          <Table striped>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t("tools.tool")}</Table.Th>
                <Table.Th>{t("common.description")}</Table.Th>
                <Table.Th>{t("tools.origin")}</Table.Th>
                <Table.Th>{t("tools.permissions")}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {tools.data?.map((tool) => (
                <Table.Tr key={tool.name}>
                  <Table.Td>
                    <Code>{tool.name}</Code>
                    {tool.requires_confirmation && (
                      <Badge size="xs" color="orange" ml={4}>
                        {t("tools.confirmation")}
                      </Badge>
                    )}
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{tool.description}</Text>
                  </Table.Td>
                  <Table.Td>{tool.owner}</Table.Td>
                  <Table.Td>{tool.permissions.join(", ")}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
