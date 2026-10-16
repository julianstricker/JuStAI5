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
  const status = useQuery({
    queryKey: ["tls"],
    queryFn: () => api.get<TlsStatus>("/api/tls/status"),
  });
  const add = useAction(
    (name: string) => api.post("/api/tls/names", { name }),
    { invalidate: [["tls"]], success: "Zertifikat erweitert" },
  );
  const s = status.data;
  if (!s) return null;
  if (!s.enabled) {
    return (
      <Card withBorder>
        <Title order={5}>Geräte-App</Title>
        <Text size="sm" c="dimmed">
          HTTPS ist deaktiviert (JUSTAI_TLS_ENABLED). Mikrofon und Kamera
          funktionieren in Browsern nur über HTTPS.
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
          <Title order={5}>Geräte-App (Handy, Tablet, PC)</Title>
          <Badge color="teal" variant="light">
            HTTPS Port {s.port}
          </Badge>
        </Group>
        <Text size="sm">
          Macht ein Gerät zu Mikrofon, Lautsprecher, Kamera und Bildschirm des
          Assistenten. Auf dem Gerät öffnen:{" "}
          <Anchor href={appUrl}>{appUrl}</Anchor>, Funktionen wählen, Code unter
          „Displays“ freigeben. Mit Mikrofon und Lautsprecher entsteht im
          gewählten Raum automatisch ein Endpoint.
        </Text>
        {!s.current_host_covered && (
          <Alert color="orange" title="Diese Adresse fehlt im Zertifikat">
            <Group justify="space-between">
              <Text size="sm">
                Das HTTPS-Zertifikat enthält <Code>{host}</Code> noch nicht.
              </Text>
              <Button
                size="xs"
                onClick={() => add.mutate(host)}
                loading={add.isPending}
              >
                Hinzufügen
              </Button>
            </Group>
          </Alert>
        )}
        <Text size="xs" c="dimmed">
          Zertifikat gilt für: {s.names?.join(", ")}
        </Text>
        <Group>
          <Button
            component="a"
            href="/api/tls/ca.crt"
            variant="light"
            size="xs"
          >
            JuStAI5-Zertifikat herunterladen
          </Button>
          <Text size="xs" c="dimmed">
            SHA-256: <Code>{s.ca_fingerprint}</Code>
          </Text>
        </Group>
        <Accordion variant="contained">
          <Accordion.Item value="howto">
            <Accordion.Control>
              Zertifikat auf Geräten installieren (einmalig, dann ohne Warnung
              und als App installierbar)
            </Accordion.Control>
            <Accordion.Panel>
              <List size="sm" spacing="xs">
                <List.Item>
                  <b>Android:</b> Zertifikat auf dem Gerät öffnen →
                  Einstellungen → Sicherheit → Verschlüsselung &amp;
                  Anmeldedaten → Zertifikat installieren → CA-Zertifikat. Dann
                  die App-Adresse in Chrome öffnen → Menü → „App installieren“.
                </List.Item>
                <List.Item>
                  <b>iPhone/iPad:</b> Zertifikat in Safari laden → Einstellungen
                  → „Profil geladen“ installieren → Allgemein → Info →
                  Zertifikatsvertrauenseinstellungen → JuStAI5 aktivieren. Dann
                  in Safari Teilen → „Zum Home-Bildschirm“.
                </List.Item>
                <List.Item>
                  <b>Windows:</b> Datei doppelklicken → Zertifikat installieren
                  → Lokaler Computer → „Vertrauenswürdige
                  Stammzertifizierungsstellen“. In Chrome/Edge: Adressleiste →
                  „App installieren“.
                </List.Item>
                <List.Item>
                  <b>macOS:</b> Datei öffnen → Schlüsselbund „System“ →
                  Zertifikat doppelklicken → Vertrauen: „Immer vertrauen“.
                </List.Item>
                <List.Item>
                  <b>Ohne Installation:</b> Die Browser-Warnung einmal
                  bestätigen genügt meist für Mikrofon und Kamera, die
                  Installation als App ist dann aber nicht möglich.
                </List.Item>
              </List>
            </Accordion.Panel>
          </Accordion.Item>
        </Accordion>
      </Stack>
    </Card>
  );
}
