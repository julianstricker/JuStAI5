import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Group,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Text,
} from "@mantine/core";
import {
  IconArrowDown,
  IconArrowLeft,
  IconArrowRight,
  IconArrowUp,
  IconHome,
  IconPlayerStop,
} from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

import { useAction } from "./common";

interface PtzStatus {
  capabilities: Record<string, unknown>;
  tracking: { active: boolean; target: string | null; state: string } | null;
  manual_override_until: number | null;
}

export function PtzPad({ deviceId }: { deviceId: string }) {
  const status = useQuery({
    queryKey: ["ptz", deviceId],
    queryFn: () => api.get<PtzStatus>(`/api/ptz/${deviceId}/status`),
    refetchInterval: 2000,
  });
  const presets = useQuery({
    queryKey: ["ptz-presets", deviceId],
    queryFn: () =>
      api.get<{ id: string; name: string }[]>(`/api/ptz/${deviceId}/presets`),
  });
  const move = useAction((d: { pan: number; tilt: number }) =>
    api.post(`/api/ptz/${deviceId}/move`, d),
  );
  const stop = useAction(() => api.post(`/api/ptz/${deviceId}/stop`));
  const home = useAction(() => api.post(`/api/ptz/${deviceId}/home`), {
    success: "Ausgangsposition",
  });
  const setHome = useAction(() => api.post(`/api/ptz/${deviceId}/home/set`), {
    success: "Aktuelle Ansicht als Home gespeichert",
    invalidate: [["ptz-presets", deviceId]],
  });
  const goto = useAction((id: string) =>
    api.post(`/api/ptz/${deviceId}/presets/${id}/goto`),
  );
  const track = useAction(
    (enable: boolean) =>
      api.post(`/api/ptz/${deviceId}/track`, { enable, target: "person" }),
    {
      invalidate: [["ptz", deviceId]],
    },
  );
  const step = 0.15;
  const tracking = status.data?.tracking;
  return (
    <Card withBorder>
      <Stack gap="xs">
        <Group justify="space-between">
          <Text fw={600}>PTZ</Text>
          {tracking?.active && (
            <Badge color="teal">
              Tracking: {tracking.target} ({tracking.state})
            </Badge>
          )}
        </Group>
        <SimpleGrid cols={3} w={150} spacing={4}>
          <div />
          <ActionIcon
            size="lg"
            onClick={() => move.mutate({ pan: 0, tilt: step })}
          >
            <IconArrowUp />
          </ActionIcon>
          <div />
          <ActionIcon
            size="lg"
            onClick={() => move.mutate({ pan: -step, tilt: 0 })}
          >
            <IconArrowLeft />
          </ActionIcon>
          <ActionIcon
            size="lg"
            color="red"
            onClick={() => stop.mutate(undefined)}
          >
            <IconPlayerStop />
          </ActionIcon>
          <ActionIcon
            size="lg"
            onClick={() => move.mutate({ pan: step, tilt: 0 })}
          >
            <IconArrowRight />
          </ActionIcon>
          <div />
          <ActionIcon
            size="lg"
            onClick={() => move.mutate({ pan: 0, tilt: -step })}
          >
            <IconArrowDown />
          </ActionIcon>
          <div />
        </SimpleGrid>
        <Group>
          <Button
            size="xs"
            variant="default"
            leftSection={<IconHome size={14} />}
            onClick={() => home.mutate(undefined)}
          >
            Home
          </Button>
          <Button
            size="xs"
            variant="subtle"
            onClick={() =>
              confirm("Aktuelle Kameraansicht als Home-Position speichern?") &&
              setHome.mutate(undefined)
            }
            loading={setHome.isPending}
          >
            Als Home speichern
          </Button>
          {!!presets.data?.length && (
            <Select
              size="xs"
              placeholder="Preset …"
              data={presets.data.map((p) => ({ value: p.id, label: p.name }))}
              value={null}
              onChange={(v) => v && goto.mutate(v)}
            />
          )}
          <Switch
            label="Person folgen"
            checked={Boolean(tracking?.active)}
            onChange={(e) => track.mutate(e.currentTarget.checked)}
          />
        </Group>
        <Text size="xs" c="dimmed">
          Manuelle Steuerung hat Vorrang und pausiert automatisches Tracking.
        </Text>
      </Stack>
    </Card>
  );
}
