// Browser display client. Pairs with the core via a short code, then renders
// presentation documents and acknowledges each one only after it is on screen.
import "@mantine/core/styles.css";

import { Box, Center, MantineProvider, Stack, Text, Title } from "@mantine/core";
import { Component, type ReactNode, StrictMode, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";

import { type PresentationDocument, Renderer } from "@/shared/render/Renderer";

const TOKEN_KEY = "justai.display.token";
const CAPABILITIES = ["display.text", "display.image", "display.dashboard", "display.video", "display.interactive", "display.notifications", "display.fullscreen"];

type Inbound =
  | { type: "pairing"; code: string }
  | { type: "paired"; token: string; name: string; room: string | null }
  | { type: "ready"; name: string; room: string | null; build?: string }
  | { type: "show"; presentation_id: string; document: PresentationDocument }
  | { type: "close"; presentation_id: string }
  | { type: "indicator"; listening: boolean; conversation: boolean; cloud: boolean }
  | { type: "error"; message: string };

let loadedBuild: string | undefined;

function useDisplayConnection() {
  const [state, setState] = useState<{ code?: string; name?: string; room?: string | null; error?: string; connected: boolean }>({ connected: false });
  const [current, setCurrent] = useState<{ id: string; document: PresentationDocument } | null>(null);
  const [indicator, setIndicator] = useState({ listening: false, conversation: false, cloud: false });
  const ws = useRef<WebSocket | null>(null);

  useEffect(() => {
    let retry = 1000;
    let closed = false;
    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const socket = new WebSocket(`${proto}://${location.host}/api/display/ws`);
      ws.current = socket;
      socket.onopen = () => {
        retry = 1000;
        setState((s) => ({ ...s, connected: true, error: undefined }));
        socket.send(JSON.stringify({ type: "hello", token: localStorage.getItem(TOKEN_KEY), capabilities: CAPABILITIES, user_agent: navigator.userAgent }));
      };
      socket.onmessage = (e) => {
        const msg = JSON.parse(e.data) as Inbound;
        if (msg.type === "pairing") setState((s) => ({ ...s, code: msg.code }));
        if (msg.type === "paired") {
          localStorage.setItem(TOKEN_KEY, msg.token);
          setState((s) => ({ ...s, code: undefined, name: msg.name, room: msg.room }));
        }
        if (msg.type === "ready") {
          // A different build after reconnecting means JuStAI5 was updated: load the new client.
          if (msg.build && loadedBuild && msg.build !== loadedBuild) window.location.reload();
          loadedBuild = msg.build ?? loadedBuild;
          setState((s) => ({ ...s, code: undefined, name: msg.name, room: msg.room }));
        }
        if (msg.type === "show") setCurrent({ id: msg.presentation_id, document: msg.document });
        if (msg.type === "close") setCurrent((c) => (c?.id === msg.presentation_id ? null : c));
        if (msg.type === "indicator") setIndicator(msg);
        if (msg.type === "error") {
          if (msg.message === "invalid token") localStorage.removeItem(TOKEN_KEY);
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
  }, []);

  const send = (msg: unknown) => ws.current?.readyState === WebSocket.OPEN && ws.current.send(JSON.stringify(msg));
  return { state, current, indicator, send };
}

/** Catches rendering errors of one presentation so the display keeps working and reports the failure. */
class PresentationBoundary extends Component<{ onError: () => void; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch() {
    this.props.onError();
  }

  render() {
    return this.state.failed ? <Text c="dimmed">Inhalt konnte nicht dargestellt werden.</Text> : this.props.children;
  }
}

function DisplayApp() {
  const { state, current, indicator, send } = useDisplayConnection();
  const renderFailed = useRef<string | null>(null);

  // Acknowledge only after React committed the presentation to the DOM.
  useEffect(() => {
    if (!current) return;
    if (document.visibilityState === "hidden") {
      // Screen off or page in the background: nobody can see it, say so instead of claiming success.
      send({ type: "ack", presentation_id: current.id, status: "failed", reason: "hidden" });
      return;
    }
    requestAnimationFrame(() =>
      renderFailed.current === current.id
        ? send({ type: "ack", presentation_id: current.id, status: "failed", reason: "render_error" })
        : send({ type: "ack", presentation_id: current.id, status: "displayed" }),
    );
  }, [current]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Box p="xl" mih="100vh" pos="relative">
      {(indicator.listening || indicator.conversation) && (
        <Text pos="fixed" top={8} right={12} size="sm" c={indicator.cloud ? "red" : indicator.conversation ? "orange" : "dimmed"}>
          ● {indicator.conversation ? (indicator.cloud ? "Gespräch (Cloud)" : "Gespräch") : "hört auf Wakeword"}
        </Text>
      )}
      {current ? (
        <PresentationBoundary key={current.id} onError={() => (renderFailed.current = current.id)}>
          <Renderer
            document={current.document}
            onInteract={(action) => send({ type: "interaction", presentation_id: current.id, ...action })}
          />
        </PresentationBoundary>
      ) : state.code ? (
        <Center h="90vh">
          <Stack align="center">
            <Title>Display koppeln</Title>
            <Text size="xl">Code im Admin-Bereich unter „Displays“ freigeben:</Text>
            <Text fz={96} fw={800} ff="monospace">
              {state.code}
            </Text>
          </Stack>
        </Center>
      ) : (
        <Center h="90vh">
          <Stack align="center">
            <Text fz={80} fw={700}>
              {new Date().toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })}
            </Text>
            <Text c="dimmed">{state.connected ? `${state.name ?? "Display"} bereit` : "Verbinde mit JuStAI5 …"}</Text>
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
      <DisplayApp />
    </MantineProvider>
  </StrictMode>,
);
