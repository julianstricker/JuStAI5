// Live feed (events + telemetry) over the admin WebSocket, shared by all pages.
import { useEffect, useRef, useState } from "react";

import type { JEvent } from "./types";

type Message =
  | { kind: "event"; event: JEvent }
  | { kind: "telemetry"; topic: string; ts: number; data: unknown };

type Listener = (m: Message) => void;

class LiveFeed {
  private ws: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private retry = 1000;
  connected = false;

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    if (!this.ws) this.connect();
    return () => {
      this.listeners.delete(fn);
    };
  }

  private connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/api/ws`);
    this.ws = ws;
    ws.onopen = () => {
      this.connected = true;
      this.retry = 1000;
    };
    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data) as Message;
      for (const l of this.listeners) l(msg);
    };
    ws.onclose = () => {
      this.connected = false;
      this.ws = null;
      setTimeout(() => this.connect(), this.retry);
      this.retry = Math.min(this.retry * 2, 15000);
    };
  }
}

export const liveFeed = new LiveFeed();

export function useLiveEvents(limit = 200, filter?: (e: JEvent) => boolean): JEvent[] {
  const [events, setEvents] = useState<JEvent[]>([]);
  const filterRef = useRef(filter);
  filterRef.current = filter;
  useEffect(
    () =>
      liveFeed.subscribe((m) => {
        if (m.kind !== "event") return;
        if (filterRef.current && !filterRef.current(m.event)) return;
        setEvents((prev) => [m.event, ...prev].slice(0, limit));
      }),
    [limit],
  );
  return events;
}

export function useTelemetry<T>(prefix: string): Record<string, T> {
  const [data, setData] = useState<Record<string, T>>({});
  useEffect(
    () =>
      liveFeed.subscribe((m) => {
        if (m.kind !== "telemetry" || !m.topic.startsWith(prefix)) return;
        setData((prev) => ({ ...prev, [m.topic.slice(prefix.length)]: m.data as T }));
      }),
    [prefix],
  );
  return data;
}
