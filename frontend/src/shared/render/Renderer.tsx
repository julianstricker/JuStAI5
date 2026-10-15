// Render engine for presentation documents. Only these trusted components exist;
// documents are data (validated by the core), never HTML or script.
import { Badge, Button, Card, Group, Image, List, Notification, SimpleGrid, Stack, Table, Text, Title } from "@mantine/core";
import { IconArrowDownRight, IconArrowRight, IconArrowUpRight } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import Markdown from "react-markdown";

import { Chart } from "./Chart";
import { LiveVideo } from "./LiveVideo";

export type Component = { type: string; [key: string]: any };

export interface PresentationDocument {
  title?: string;
  layout?: "single" | "dashboard" | "fullscreen";
  theme?: "auto" | "dark" | "light";
  components: Component[];
}

export type InteractionHandler = (action: { component: string; action_id?: string; option_id?: string; label?: string }) => void;

function Clock({ show_date = true }: { show_date?: boolean }) {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  return (
    <Stack gap={0} align="center">
      <Text fz={64} fw={700}>
        {now.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })}
      </Text>
      {show_date && <Text c="dimmed">{now.toLocaleDateString("de-DE", { weekday: "long", day: "numeric", month: "long" })}</Text>}
    </Stack>
  );
}

const TREND = {
  up: { icon: IconArrowUpRight, color: "teal" },
  down: { icon: IconArrowDownRight, color: "red" },
  flat: { icon: IconArrowRight, color: "gray" },
};

function Render({ c, onInteract }: { c: Component; onInteract: InteractionHandler }) {
  switch (c.type) {
    case "text":
      return (
        <Text size={{ s: "sm", m: "md", l: "lg", xl: "xl" }[c.size as string] ?? "md"} ta={c.align}>
          {c.text}
        </Text>
      );
    case "heading":
      return <Title order={(c.level ?? 1) as 1 | 2 | 3}>{c.text}</Title>;
    case "markdown":
      // react-markdown does not render raw HTML unless explicitly enabled.
      return <Markdown>{c.markdown}</Markdown>;
    case "image":
      return <Image src={c.src} alt={c.alt} fit={c.fit} radius="md" mah="70vh" />;
    case "table":
      return (
        <Table striped withTableBorder>
          {c.caption && <Table.Caption>{c.caption}</Table.Caption>}
          <Table.Thead>
            <Table.Tr>
              {(c.columns as string[]).map((col) => (
                <Table.Th key={col}>{col}</Table.Th>
              ))}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {(c.rows as unknown[][]).map((row, i) => (
              <Table.Tr key={i}>
                {row.map((cell, j) => (
                  <Table.Td key={j}>{cell === null ? "–" : String(cell)}</Table.Td>
                ))}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      );
    case "kv":
      return (
        <Table>
          <Table.Tbody>
            {(c.items as { label: string; value: string | number }[]).map((it) => (
              <Table.Tr key={it.label}>
                <Table.Td c="dimmed">{it.label}</Table.Td>
                <Table.Td fw={600}>{String(it.value)}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      );
    case "stat": {
      const trend = c.trend ? TREND[c.trend as keyof typeof TREND] : null;
      return (
        <Card withBorder>
          <Text c="dimmed" size="sm">
            {c.label}
          </Text>
          <Group gap="xs" align="baseline">
            <Text fz={36} fw={700}>
              {String(c.value)}
            </Text>
            {c.unit && <Text>{c.unit}</Text>}
            {trend && <trend.icon color={`var(--mantine-color-${trend.color}-6)`} />}
            {c.delta && <Text c={trend?.color}>{c.delta}</Text>}
          </Group>
        </Card>
      );
    }
    case "chart":
      return <Chart spec={c as any} />;
    case "list":
      return (
        <List type={c.ordered ? "ordered" : "unordered"} size="lg">
          {(c.items as string[]).map((it, i) => (
            <List.Item key={i}>{it}</List.Item>
          ))}
        </List>
      );
    case "weather":
      return (
        <Card withBorder>
          <Text c="dimmed">{c.location}</Text>
          <Group align="baseline">
            {c.temperature !== undefined && (
              <Text fz={48} fw={700}>
                {Math.round(c.temperature)}
                {c.unit}
              </Text>
            )}
            <Text size="lg">{c.condition}</Text>
          </Group>
          <Group mt="sm">
            {(c.forecast ?? []).map((f: any) => (
              <Stack key={f.day} gap={0} align="center">
                <Text size="sm">{f.day}</Text>
                <Text size="xs" c="dimmed">
                  {f.condition}
                </Text>
                <Text size="sm">
                  {f.min !== null && f.min !== undefined ? Math.round(f.min) : "–"}° / {f.max !== null && f.max !== undefined ? Math.round(f.max) : "–"}°
                </Text>
              </Stack>
            ))}
          </Group>
        </Card>
      );
    case "stock-quote": {
      const up = (c.change ?? 0) >= 0;
      return (
        <Card withBorder>
          <Group justify="space-between">
            <Stack gap={0}>
              <Text fw={700} size="lg">
                {c.symbol}
              </Text>
              {c.name && (
                <Text size="xs" c="dimmed">
                  {c.name}
                </Text>
              )}
            </Stack>
            <Stack gap={0} align="flex-end">
              <Text fz={28} fw={700}>
                {Number(c.price).toFixed(2)} {c.currency}
              </Text>
              {c.change_pct !== undefined && (
                <Badge color={up ? "teal" : "red"}>
                  {up ? "+" : ""}
                  {Number(c.change_pct).toFixed(2)} %
                </Badge>
              )}
            </Stack>
          </Group>
          {c.time && (
            <Text size="xs" c="dimmed">
              Stand {c.time}
            </Text>
          )}
        </Card>
      );
    }
    case "camera":
      return c.src ? (
        <LiveVideo src={c.src} />
      ) : (
        <Text c="dimmed">Kamerabild nicht verfügbar</Text>
      );
    case "notification":
      return (
        <Notification withCloseButton={false} color={{ info: "blue", success: "green", warning: "orange", error: "red" }[c.level as string]} title={c.title}>
          {c.message}
        </Notification>
      );
    case "choice":
      return (
        <Stack>
          <Text size="lg" fw={600}>
            {c.prompt}
          </Text>
          <Group>
            {(c.options as { id: string; label: string }[]).map((o) => (
              <Button key={o.id} size="lg" onClick={() => onInteract({ component: "choice", option_id: o.id, label: o.label })}>
                {o.label}
              </Button>
            ))}
          </Group>
        </Stack>
      );
    case "button":
      return (
        <Button size="lg" onClick={() => onInteract({ component: "button", action_id: c.action_id, label: c.label })}>
          {c.label}
        </Button>
      );
    case "clock":
      return <Clock show_date={c.show_date} />;
    case "card":
      return (
        <Card withBorder>
          {c.title && (
            <Title order={4} mb="sm">
              {c.title}
            </Title>
          )}
          <Stack>{(c.children as Component[]).map((child, i) => <Render key={i} c={child} onInteract={onInteract} />)}</Stack>
        </Card>
      );
    case "row":
      return (
        <Group grow align="stretch">
          {(c.children as Component[]).map((child, i) => (
            <Render key={i} c={child} onInteract={onInteract} />
          ))}
        </Group>
      );
    case "grid":
      return (
        <SimpleGrid cols={{ base: 1, sm: Math.min(2, c.columns ?? 2), lg: c.columns ?? 2 }}>
          {(c.children as Component[]).map((child, i) => (
            <Render key={i} c={child} onInteract={onInteract} />
          ))}
        </SimpleGrid>
      );
    default:
      return <Text c="red">Unbekannte Komponente: {c.type}</Text>;
  }
}

export function Renderer({ document, onInteract }: { document: PresentationDocument; onInteract: InteractionHandler }) {
  const dashboard = document.layout === "dashboard";
  return (
    <Stack gap="lg">
      {document.title && <Title order={1}>{document.title}</Title>}
      {dashboard ? (
        <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }}>
          {document.components.map((c, i) => (
            <Render key={i} c={c} onInteract={onInteract} />
          ))}
        </SimpleGrid>
      ) : (
        document.components.map((c, i) => <Render key={i} c={c} onInteract={onInteract} />)
      )}
    </Stack>
  );
}
