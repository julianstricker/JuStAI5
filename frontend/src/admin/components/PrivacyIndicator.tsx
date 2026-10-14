// Shows what is in use right now: local wakeword listening, active conversations,
// cloud audio and local vision (requirement 23.3).
import { Badge, Group, HoverCard, Stack, Text } from "@mantine/core";
import { IconCloud, IconEar, IconEye, IconMicrophone } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";

interface Indicator {
  endpoint_id?: string;
  device_id?: string;
  room_id?: string;
  wakeword_local?: boolean;
  conversation_active?: boolean;
  cloud_audio?: boolean;
  vision_local?: boolean;
  muted?: boolean;
}

export function PrivacyIndicator() {
  const { data } = useQuery({
    queryKey: ["status"],
    queryFn: () => api.get<{ privacy: Indicator[] }>("/api/system/status"),
    refetchInterval: 3000,
  });
  const items = data?.privacy ?? [];
  const listening = items.filter((i) => i.wakeword_local).length;
  const conversations = items.filter((i) => i.conversation_active).length;
  const cloud = items.filter((i) => i.cloud_audio).length;
  const vision = items.filter((i) => i.vision_local).length;
  return (
    <HoverCard width={280} shadow="md">
      <HoverCard.Target>
        <Group gap={6}>
          <Badge leftSection={<IconEar size={12} />} variant="light" color="gray">
            {listening}
          </Badge>
          <Badge leftSection={<IconMicrophone size={12} />} variant={conversations ? "filled" : "light"} color={conversations ? "orange" : "gray"}>
            {conversations}
          </Badge>
          <Badge leftSection={<IconCloud size={12} />} variant={cloud ? "filled" : "light"} color={cloud ? "red" : "gray"}>
            {cloud}
          </Badge>
          <Badge leftSection={<IconEye size={12} />} variant="light" color={vision ? "blue" : "gray"}>
            {vision}
          </Badge>
        </Group>
      </HoverCard.Target>
      <HoverCard.Dropdown>
        <Stack gap={4}>
          <Text size="sm">
            <IconEar size={12} /> {listening} Endpunkte hören lokal auf das Wakeword
          </Text>
          <Text size="sm">
            <IconMicrophone size={12} /> {conversations} aktive Gespräche
          </Text>
          <Text size="sm">
            <IconCloud size={12} /> {cloud} Gespräche übertragen Audio an einen Cloud-Dienst
          </Text>
          <Text size="sm">
            <IconEye size={12} /> {vision} Kameras mit lokaler Bildanalyse
          </Text>
        </Stack>
      </HoverCard.Dropdown>
    </HoverCard>
  );
}
