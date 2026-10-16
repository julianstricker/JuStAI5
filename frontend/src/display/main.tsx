// JuStAI5 app for phones, tablets and PCs (also the plain browser display).
// Pairs with the core via a short code. Depending on the chosen features the device
// is a screen and/or microphone, speaker and camera of the assistant. Presentations
// are acknowledged only after they are on screen.
import "@mantine/core/styles.css";

import {
  ActionIcon,
  Alert,
  Anchor,
  Box,
  Button,
  Center,
  Group,
  MantineProvider,
  SegmentedControl,
  Stack,
  Switch,
  Text,
  Title,
} from "@mantine/core";
import { IconSettings } from "@tabler/icons-react";
import {
  Component,
  type ReactNode,
  StrictMode,
  useEffect,
  useRef,
  useState,
} from "react";
import { createRoot } from "react-dom/client";

import { type PresentationDocument, Renderer } from "@/shared/render/Renderer";

import {
  type CameraMode,
  capabilitiesFor,
  DeviceMedia,
  type MediaFeatures,
  SPEAKER,
} from "./media";

const TOKEN_KEY = "justai.display.token";
const FEATURES_KEY = "justai.app.features";
const DISPLAY_CAPABILITIES = [
  "display.text",
  "display.image",
  "display.dashboard",
  "display.video",
  "display.interactive",
  "display.notifications",
  "display.fullscreen",
];

type Inbound =
  | { type: "pairing"; code: string }
  | { type: "paired"; token: string; name: string; room: string | null }
  | { type: "ready"; name: string; room: string | null; build?: string }
  | { type: "show"; presentation_id: string; document: PresentationDocument }
  | { type: "close"; presentation_id: string }
  | {
      type: "indicator";
      listening: boolean;
      conversation: boolean;
      cloud: boolean;
    }
  | { type: "error"; message: string };

let loadedBuild: string | undefined;

function loadFeatures(): MediaFeatures | null {
  try {
    const raw = localStorage.getItem(FEATURES_KEY);
    if (raw) return JSON.parse(raw) as MediaFeatures;
    // Displays paired before the app existed stay pure displays.
    if (localStorage.getItem(TOKEN_KEY))
      return { mic: false, speaker: false, camera: "off" };
  } catch {
    /* storage unavailable */
  }
  return null;
}

function useConnection(
  capabilities: string[] | null,
  onBinary: (data: ArrayBuffer) => void,
) {
  const [state, setState] = useState<{
    code?: string;
    name?: string;
    room?: string | null;
    error?: string;
    connected: boolean;
  }>({ connected: false });
  const [current, setCurrent] = useState<{
    id: string;
    document: PresentationDocument;
  } | null>(null);
  const [indicator, setIndicator] = useState({
    listening: false,
    conversation: false,
    cloud: false,
  });
  const ws = useRef<WebSocket | null>(null);
  const binary = useRef(onBinary);
  useEffect(() => {
    binary.current = onBinary;
  });
  const capsKey = capabilities ? capabilities.join(",") : null;

  useEffect(() => {
    if (capsKey === null) return;
    let retry = 1000;
    let closed = false;
    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const socket = new WebSocket(
        `${proto}://${location.host}/api/display/ws`,
      );
      socket.binaryType = "arraybuffer";
      ws.current = socket;
      socket.onopen = () => {
        retry = 1000;
        setState((s) => ({ ...s, connected: true, error: undefined }));
        socket.send(
          JSON.stringify({
            type: "hello",
            token: localStorage.getItem(TOKEN_KEY),
            capabilities: capsKey.split(","),
            user_agent: navigator.userAgent,
          }),
        );
      };
      socket.onmessage = (e: MessageEvent<string | ArrayBuffer>) => {
        if (typeof e.data !== "string") {
          binary.current(e.data);
          return;
        }
        const msg = JSON.parse(e.data) as Inbound;
        if (msg.type === "pairing") setState((s) => ({ ...s, code: msg.code }));
        if (msg.type === "paired") {
          localStorage.setItem(TOKEN_KEY, msg.token);
          setState((s) => ({
            ...s,
            code: undefined,
            name: msg.name,
            room: msg.room,
          }));
        }
        if (msg.type === "ready") {
          // A different build after reconnecting means JuStAI5 was updated: load the new client.
          if (msg.build && loadedBuild && msg.build !== loadedBuild)
            window.location.reload();
          loadedBuild = msg.build ?? loadedBuild;
          setState((s) => ({
            ...s,
            code: undefined,
            name: msg.name,
            room: msg.room,
          }));
        }
        if (msg.type === "show")
          setCurrent({ id: msg.presentation_id, document: msg.document });
        if (msg.type === "close")
          setCurrent((c) => (c?.id === msg.presentation_id ? null : c));
        if (msg.type === "indicator") setIndicator(msg);
        if (msg.type === "error") {
          if (msg.message === "invalid token")
            localStorage.removeItem(TOKEN_KEY);
          setState((s) => ({ ...s, error: msg.message }));
        }
      };
      socket.onclose = () => {
        setState((s) => ({ ...s, connected: false }));
        if (!closed) setTimeout(connect, (retry = Math.min(retry * 2, 15000)));
      };
    };
    connect();
    return () => {
      closed = true;
      ws.current?.close();
    };
  }, [capsKey]);

  const send = (msg: unknown) =>
    ws.current?.readyState === WebSocket.OPEN &&
    ws.current.send(JSON.stringify(msg));
  const sendBinary = (data: ArrayBuffer | Blob) => {
    // Drop media instead of queueing it when the network is slow (real time matters).
    if (
      ws.current?.readyState === WebSocket.OPEN &&
      ws.current.bufferedAmount < 512 * 1024
    )
      ws.current.send(data);
  };
  return { state, current, indicator, send, sendBinary };
}

/** Catches rendering errors of one presentation so the display keeps working and reports the failure. */
class PresentationBoundary extends Component<
  { onError: () => void; children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch() {
    this.props.onError();
  }

  render() {
    return this.state.failed ? (
      <Text c="dimmed">Inhalt konnte nicht dargestellt werden.</Text>
    ) : (
      this.props.children
    );
  }
}

function Setup({
  initial,
  onDone,
}: {
  initial: MediaFeatures;
  onDone: (f: MediaFeatures) => void;
}) {
  const [f, setF] = useState(initial);
  const needsSecure = (f.mic || f.camera !== "off") && !window.isSecureContext;
  const httpsUrl = `https://${location.hostname}:8443${location.pathname}`;
  return (
    <Center mih="100vh" p="md">
      <Stack maw={460} w="100%">
        <Title order={2}>JuStAI5 auf diesem Gerät</Title>
        <Text c="dimmed">
          Was soll dieses Gerät für den Assistenten sein? Der Bildschirm zeigt
          immer Inhalte an.
        </Text>
        <Switch
          size="md"
          label="Mikrofon – zuhören und auf „Hey Jarvis“ reagieren"
          checked={f.mic}
          onChange={(e) => setF({ ...f, mic: e.currentTarget.checked })}
        />
        <Switch
          size="md"
          label="Lautsprecher – Antworten hier ausgeben"
          checked={f.speaker}
          onChange={(e) => setF({ ...f, speaker: e.currentTarget.checked })}
        />
        <Stack gap={4}>
          <Text size="sm">Kamera</Text>
          <SegmentedControl
            value={f.camera}
            onChange={(v) => setF({ ...f, camera: v as CameraMode })}
            data={[
              { label: "Aus", value: "off" },
              { label: "Vorne", value: "user" },
              { label: "Hinten", value: "environment" },
            ]}
          />
        </Stack>
        {needsSecure && (
          <Alert color="orange" title="HTTPS nötig">
            Browser erlauben Mikrofon und Kamera nur über HTTPS. Öffne{" "}
            <Anchor href={httpsUrl}>{httpsUrl}</Anchor>. Damit keine Warnung
            erscheint, einmal das{" "}
            <Anchor href="/api/tls/ca.crt">JuStAI5-Zertifikat</Anchor> auf
            diesem Gerät installieren (Anleitung in der Admin-Oberfläche unter
            Einstellungen).
          </Alert>
        )}
        <Button size="lg" onClick={() => onDone(f)} disabled={needsSecure}>
          Starten
        </Button>
      </Stack>
    </Center>
  );
}

function App() {
  const [features, setFeatures] = useState<MediaFeatures | null>(loadFeatures);
  const [setupOpen, setSetupOpen] = useState(features === null);
  const [running, setRunning] = useState(false);
  const [mediaError, setMediaError] = useState<string | null>(null);
  const [level, setLevel] = useState(0);
  const media = useRef<DeviceMedia | null>(null);
  const previewRef = useRef<HTMLDivElement | null>(null);
  const renderFailed = useRef<string | null>(null);

  // Capabilities follow the chosen features (not whether media already runs): otherwise the
  // pairing code would change after the first tap.
  const capabilities =
    features && !setupOpen
      ? [...DISPLAY_CAPABILITIES, ...capabilitiesFor(features)]
      : null;
  const { state, current, indicator, send, sendBinary } = useConnection(
    capabilities,
    (data) => {
      const bytes = new Uint8Array(data);
      if (bytes[0] === SPEAKER) media.current?.play(data.slice(1));
    },
  );
  const sendBinaryRef = useRef(sendBinary);
  useEffect(() => {
    sendBinaryRef.current = sendBinary;
  });

  const needsMedia =
    !!features &&
    (features.mic || features.speaker || features.camera !== "off");

  // Microphone/camera need a user gesture (autoplay and permission rules): start on tap.
  const start = async (f: MediaFeatures) => {
    setMediaError(null);
    try {
      media.current ??= new DeviceMedia((d) => sendBinaryRef.current(d));
      await media.current.start(f);
      if (previewRef.current && f.camera !== "off") {
        const v = media.current.video;
        v.style.width = "100%";
        v.style.borderRadius = "8px";
        previewRef.current.replaceChildren(v);
      }
      setRunning(true);
    } catch (err) {
      setRunning(false);
      setMediaError(
        err instanceof Error ? `${err.name}: ${err.message}` : String(err),
      );
    }
  };

  // Keep the screen on while the app runs; refresh the mic level indicator.
  useEffect(() => {
    if (!running) return;
    let lock: { release: () => Promise<void> } | null = null;
    const acquire = () => {
      const wl = (
        navigator as Navigator & {
          wakeLock?: {
            request: (t: "screen") => Promise<{ release: () => Promise<void> }>;
          };
        }
      ).wakeLock;
      wl?.request("screen")
        .then((l) => (lock = l))
        .catch(() => undefined);
    };
    acquire();
    const onVisible = () => document.visibilityState === "visible" && acquire();
    document.addEventListener("visibilitychange", onVisible);
    const timer = window.setInterval(() => setLevel(media.current?.micLevel ?? 0), 250);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      window.clearInterval(timer);
      void lock?.release();
    };
  }, [running]);

  // Installable app: register the service worker (needs HTTPS).
  useEffect(() => {
    if (window.isSecureContext && "serviceWorker" in navigator)
      navigator.serviceWorker.register("/sw.js").catch(() => undefined);
  }, []);

  // Acknowledge only after React committed the presentation to the DOM.
  useEffect(() => {
    if (!current) return;
    if (document.visibilityState === "hidden") {
      // Screen off or page in the background: nobody can see it, say so instead of claiming success.
      send({
        type: "ack",
        presentation_id: current.id,
        status: "failed",
        reason: "hidden",
      });
      return;
    }
    requestAnimationFrame(() =>
      renderFailed.current === current.id
        ? send({
            type: "ack",
            presentation_id: current.id,
            status: "failed",
            reason: "render_error",
          })
        : send({
            type: "ack",
            presentation_id: current.id,
            status: "displayed",
          }),
    );
  }, [current]); // eslint-disable-line react-hooks/exhaustive-deps

  if (setupOpen || !features) {
    return (
      <Setup
        initial={features ?? { mic: true, speaker: true, camera: "off" }}
        onDone={(f) => {
          localStorage.setItem(FEATURES_KEY, JSON.stringify(f));
          setFeatures(f);
          setSetupOpen(false);
          if (f.mic || f.speaker || f.camera !== "off") void start(f);
          else void media.current?.stop().then(() => setRunning(false));
        }}
      />
    );
  }

  return (
    <Box p="xl" mih="100vh" pos="relative">
      <Group pos="fixed" top={8} right={12} gap="xs" style={{ zIndex: 10 }}>
        {running && features.mic && (
          <Text size="sm" c="teal">
            🎤 {"▮".repeat(Math.min(5, Math.round(level * 25)))}
          </Text>
        )}
        {(indicator.listening || indicator.conversation) && (
          <Text
            size="sm"
            c={
              indicator.cloud
                ? "red"
                : indicator.conversation
                  ? "orange"
                  : "dimmed"
            }
          >
            ●{" "}
            {indicator.conversation
              ? indicator.cloud
                ? "Gespräch (Cloud)"
                : "Gespräch"
              : "hört auf Wakeword"}
          </Text>
        )}
        <ActionIcon
          variant="subtle"
          color="gray"
          onClick={() => setSetupOpen(true)}
          aria-label="Einstellungen"
        >
          <IconSettings size={18} />
        </ActionIcon>
      </Group>
      <Box
        pos="fixed"
        bottom={12}
        right={12}
        w={160}
        style={{
          zIndex: 10,
          display: running && features.camera !== "off" ? "block" : "none",
        }}
        ref={previewRef}
      />
      {needsMedia && !running ? (
        <Center h="90vh">
          <Stack align="center">
            <Button size="xl" onClick={() => void start(features)}>
              Tippen zum Starten
            </Button>
            <Text c="dimmed" ta="center" maw={420}>
              Mikrofon, Lautsprecher und Kamera dürfen erst nach einer Berührung
              starten.
            </Text>
            {mediaError && (
              <Alert color="red" maw={460}>
                Konnte nicht starten ({mediaError}). Zugriff auf Mikrofon/Kamera
                erlauben; über HTTPS öffnen.
              </Alert>
            )}
          </Stack>
        </Center>
      ) : current ? (
        <PresentationBoundary
          key={current.id}
          onError={() => (renderFailed.current = current.id)}
        >
          <Renderer
            document={current.document}
            onInteract={(action) =>
              send({
                type: "interaction",
                presentation_id: current.id,
                ...action,
              })
            }
          />
        </PresentationBoundary>
      ) : state.code ? (
        <Center h="90vh">
          <Stack align="center">
            <Title>Gerät koppeln</Title>
            <Text size="xl" ta="center">
              Code in der Admin-Oberfläche unter „Displays“ freigeben:
            </Text>
            <Text fz={96} fw={800} ff="monospace">
              {state.code}
            </Text>
          </Stack>
        </Center>
      ) : (
        <Center h="90vh">
          <Stack align="center">
            <Text fz={80} fw={700}>
              {new Date().toLocaleTimeString("de-DE", {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </Text>
            <Text c="dimmed">
              {state.connected
                ? `${state.name ?? "Gerät"} bereit${state.room ? ` · ${state.room}` : ""}`
                : "Verbinde mit JuStAI5 …"}
            </Text>
            {state.error && <Text c="red">{state.error}</Text>}
          </Stack>
        </Center>
      )}
    </Box>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MantineProvider defaultColorScheme="dark">
      <App />
    </MantineProvider>
  </StrictMode>,
);
