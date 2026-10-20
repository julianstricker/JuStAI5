import {
  Accordion,
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Code,
  Group,
  List,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { rich, useT } from "@/shared/i18n";

import { useAction } from "./common";

interface TlsStatus {
  enabled: boolean;
  port?: number;
  names?: string[];
  ca_fingerprint?: string;
  current_host?: string;
  current_host_covered?: boolean;
}

/** Device app (phones, tablets, PCs) and the HTTPS setup it needs. */
export function DeviceAppCard() {
  const t = useT();
  const status = useQuery({
    queryKey: ["tls"],
    queryFn: () => api.get<TlsStatus>("/api/tls/status"),
  });
  const add = useAction(
    (name: string) => api.post("/api/tls/names", { name }),
    { invalidate: [["tls"]], success: t("app.certExtended") },
  );
  const s = status.data;
  if (!s) return null;
  if (!s.enabled) {
    return (
      <Card withBorder>
        <Title order={5}>{t("app.title")}</Title>
        <Text size="sm" c="dimmed">
          {t("app.httpsOff")}
        </Text>
      </Card>
    );
  }
  const host = s.current_host || location.hostname;
  const appUrl = `https://${host}:${s.port}/app`;
  return (
    <Card withBorder>
      <Stack>
        <Group justify="space-between">
          <Title order={5}>{t("app.titleLong")}</Title>
          <Badge color="teal" variant="light">
            {t("app.port", { port: s.port ?? "" })}
          </Badge>
        </Group>
        <Text size="sm">
          {rich(t("app.intro"), {
            url: <Anchor href={appUrl}>{appUrl}</Anchor>,
          })}
        </Text>
        {!s.current_host_covered && (
          <Alert color="orange" title={t("app.missingTitle")}>
            <Group justify="space-between">
              <Text size="sm">
                {rich(t("app.missing"), { host: <Code>{host}</Code> })}
              </Text>
              <Button
                size="xs"
                onClick={() => add.mutate(host)}
                loading={add.isPending}
              >
                {t("common.add")}
              </Button>
            </Group>
          </Alert>
        )}
        <Text size="xs" c="dimmed">
          {t("app.validFor", { names: s.names?.join(", ") ?? "" })}
        </Text>
        <Group>
          <Button
            component="a"
            href="/api/tls/ca.crt"
            variant="light"
            size="xs"
          >
            {t("app.download")}
          </Button>
          <Text size="xs" c="dimmed">
            SHA-256: <Code>{s.ca_fingerprint}</Code>
          </Text>
        </Group>
        <Accordion variant="contained">
          <Accordion.Item value="howto">
            <Accordion.Control>{t("app.howto")}</Accordion.Control>
            <Accordion.Panel>
              <List size="sm" spacing="xs">
                <List.Item>
                  <b>Android:</b> {t("app.android")}
                </List.Item>
                <List.Item>
                  <b>iPhone/iPad:</b> {t("app.ios")}
                </List.Item>
                <List.Item>
                  <b>Windows:</b> {t("app.windows")}
                </List.Item>
                <List.Item>
                  <b>macOS:</b> {t("app.macos")}
                </List.Item>
                <List.Item>{t("app.noInstall")}</List.Item>
              </List>
            </Accordion.Panel>
          </Accordion.Item>
        </Accordion>
      </Stack>
    </Card>
  );
}
