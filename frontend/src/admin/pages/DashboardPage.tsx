import {
  Badge,
  Card,
  Group,
  Progress,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { useT } from "@/shared/i18n";
import { useLiveEvents } from "@/shared/live";
import type { ActiveSession, Device, Room } from "@/shared/types";

import { PageHeader, StatusBadge, fmtTime } from "../components/common";

interface Status {
  uptime_s: number;
  resources: {
    cpu_percent: number;
    process_cpu_percent: number;
    memory_mb: number;
    system_memory_percent: number;
    load_avg: number[];
  };
  devices: { total: number; online: number };
  plugins: { total: number; running: number; failed: string[] };
  conversations: number;
  ai_cost_today_usd: number;
  go2rtc: boolean;
  events: { published: number; persisted: number; loops_stopped: number };
}

interface AIStatus {
  roles: Record<
    string,
    {
      usable: { provider: string; model: string; locality: string }[];
      skipped: string[];
    }
  >;
  cooldowns?: Record<string, number>; // "provider/model" -> seconds paused after errors
}

function Stat({
  label,
  value,
  sub,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
}) {
  return (
    <Card withBorder>
      <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
        {label}
      </Text>
      <Text size="xl" fw={700}>
        {value}
      </Text>
      {sub && (
        <Text size="xs" c="dimmed">
          {sub}
        </Text>
      )}
    </Card>
  );
}

export function DashboardPage() {
  const status = useQuery({
    queryKey: ["status"],
    queryFn: () => api.get<Status>("/api/system/status"),
    refetchInterval: 3000,
  });
  const rooms = useQuery({
    queryKey: ["rooms"],
    queryFn: () => api.get<Room[]>("/api/rooms"),
  });
  const devices = useQuery({
    queryKey: ["devices"],
    queryFn: () => api.get<Device[]>("/api/devices"),
    refetchInterval: 5000,
  });
  const sessions = useQuery({
    queryKey: ["sessions"],
    queryFn: () => api.get<ActiveSession[]>("/api/conversations/active"),
    refetchInterval: 1500,
  });
  const ai = useQuery({
    queryKey: ["ai-status"],
    queryFn: () => api.get<AIStatus>("/api/ai/status"),
    refetchInterval: 15000,
  });
  const events = useLiveEvents(
    30,
    (e) =>
      !e.type.startsWith("conversation.state") && e.type !== "tool.executed",
  );
  const s = status.data;
  const t = useT();

  return (
    <Stack>
      <PageHeader title={t("nav.dashboard")} description={t("dash.desc")} />
      <SimpleGrid cols={{ base: 2, md: 5 }}>
        <Stat
          label={t("dash.devicesOnline")}
          value={s ? `${s.devices.online}/${s.devices.total}` : "–"}
        />
        <Stat label={t("dash.conversations")} value={s?.conversations ?? "–"} />
        <Stat
          label={t("dash.plugins")}
          value={s ? `${s.plugins.running}/${s.plugins.total}` : "–"}
          sub={
            s?.plugins.failed.length
              ? t("dash.pluginErrors", { list: s.plugins.failed.join(", ") })
              : undefined
          }
        />
        <Stat
          label={t("dash.aiCostToday")}
          value={s ? `${s.ai_cost_today_usd.toFixed(3)} $` : "–"}
        />
        <Stat
          label={t("dash.mediaServer")}
          value={s ? (s.go2rtc ? "OK" : t("dash.unreachable")) : "–"}
        />
      </SimpleGrid>

      {s && (
        <Card withBorder>
          <Group grow>
            <Stack gap={4}>
              <Text size="sm">
                {t("dash.cpu", { p: s.resources.cpu_percent.toFixed(0) })}
              </Text>
              <Progress value={s.resources.cpu_percent} />
            </Stack>
            <Stack gap={4}>
              <Text size="sm">
                {t("dash.ram", {
                  p: s.resources.system_memory_percent.toFixed(0),
                })}
              </Text>
              <Progress
                value={s.resources.system_memory_percent}
                color="teal"
              />
            </Stack>
            <Stack gap={4}>
              <Text size="sm">
                {t("dash.coreProcess", {
                  mb: s.resources.memory_mb.toFixed(0),
                })}
              </Text>
              <Text size="xs" c="dimmed">
                Load {s.resources.load_avg.map((l) => l.toFixed(2)).join(" / ")}
              </Text>
            </Stack>
          </Group>
        </Card>
      )}

      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        <Card withBorder>
          <Title order={4} mb="sm">
            {t("dash.rooms")}
          </Title>
          <Stack gap="xs">
            {rooms.data?.map((room) => (
              <Group key={room.id} justify="space-between">
                <Text fw={600}>{room.name}</Text>
                <Group gap={4}>
                  {devices.data
                    ?.filter((d) => d.room_id === room.id)
                    .map((d) => (
                      <Badge
                        key={d.id}
                        color={d.status === "online" ? "green" : "red"}
                        variant="light"
                      >
                        {d.name}
                      </Badge>
                    ))}
                </Group>
              </Group>
            ))}
            {!rooms.data?.length && <Text c="dimmed">{t("dash.noRooms")}</Text>}
          </Stack>
        </Card>
        <Card withBorder>
          <Title order={4} mb="sm">
            {t("dash.runningConversations")}
          </Title>
          {sessions.data?.length ? (
            sessions.data.map((sess) => (
              <Stack key={sess.id} gap={4} mb="sm">
                <Group gap="xs">
                  <StatusBadge status={sess.state} />
                  <Text fw={600}>{sess.room ?? t("dash.text")}</Text>
                  <Badge variant="outline">{sess.mode}</Badge>
                  {sess.person && <Badge color="teal">{sess.person}</Badge>}
                </Group>
                {sess.transcript.slice(-3).map((turn, i) => (
                  <Text
                    key={i}
                    size="sm"
                    c={turn.role === "user" ? undefined : "indigo"}
                  >
                    <b>
                      {turn.role === "user"
                        ? t("role.user")
                        : t("role.assistant")}
                      :
                    </b>{" "}
                    {turn.text}
                  </Text>
                ))}
              </Stack>
            ))
          ) : (
            <Text c="dimmed">{t("dash.noConversation")}</Text>
          )}
        </Card>
      </SimpleGrid>

      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        <Card withBorder>
          <Title order={4} mb="sm">
            {t("dash.aiProviders")}
          </Title>
          <Table>
            <Table.Tbody>
              {Object.entries(ai.data?.roles ?? {}).map(([role, info]) => (
                <Table.Tr key={role}>
                  <Table.Td>{role}</Table.Td>
                  <Table.Td>
                    {info.usable?.length ? (
                      info.usable.map((u) => {
                        const paused =
                          ai.data?.cooldowns?.[`${u.provider}/${u.model}`];
                        return (
                          <Badge
                            key={u.provider + u.model}
                            mr={4}
                            color={
                              paused
                                ? "orange"
                                : u.locality === "local"
                                  ? "green"
                                  : "blue"
                            }
                            variant="light"
                            title={
                              paused
                                ? t("dash.pausedTitle", {
                                    s: Math.ceil(paused),
                                  })
                                : undefined
                            }
                          >
                            {u.provider} {u.model}
                            {paused ? t("dash.paused") : ""}
                          </Badge>
                        );
                      })
                    ) : (
                      <Text size="xs" c="dimmed">
                        {info.skipped?.join("; ") || t("dash.notConfigured")}
                      </Text>
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Card>
        <Card withBorder>
          <Title order={4} mb="sm">
            {t("dash.recentEvents")}
          </Title>
          <Stack gap={2}>
            {events.map((e) => (
              <Text key={e.id} size="xs" ff="monospace">
                {fmtTime(e.timestamp)} {e.type}
              </Text>
            ))}
            {!events.length && (
              <Text c="dimmed">{t("dash.waitingEvents")}</Text>
            )}
          </Stack>
        </Card>
      </SimpleGrid>
    </Stack>
  );
}
