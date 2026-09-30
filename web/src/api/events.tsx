/** Server-Sent Events des Druckdienstes: eine Verbindung, Wiederverbinden mit Backoff, Query-Invalidierung. */
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import { authUrl, getToken } from './client';
import { qk } from './core';

export type ServerEventName = 'hello' | 'state' | 'status' | 'progress' | 'warning' | 'cut_pause' | 'job' | 'queue' | 'config';

const EVENT_NAMES: ServerEventName[] = ['hello', 'state', 'status', 'progress', 'warning', 'cut_pause', 'job', 'queue', 'config'];
const BACKOFF_MS = [1000, 2000, 5000, 10000];

type Handler = (data: unknown) => void;

interface EventsContextValue {
  subscribe(name: ServerEventName, handler: Handler): () => void;
  connected: boolean;
}

const EventsContext = createContext<EventsContextValue | null>(null);

function invalidateFor(client: QueryClient, name: ServerEventName, data: unknown): void {
  const keys: (readonly string[])[] = [];
  if (name === 'state' || name === 'status') keys.push(qk.status);
  else if (name === 'queue') keys.push(qk.queue);
  else if (name === 'job' && (data as { phase?: string } | null)?.phase === 'fertig') {
    keys.push(qk.history, qk.recentTexts, qk.queue, qk.stats, qk.rolls);
  } else if (name === 'config') {
    keys.push(qk.app, qk.settings, qk.tapes, ['access'], ['secrets']);
    // Module ein- oder ausgeschaltet: Modulliste, Vorlagen und Galerie folgen (Modulvorlagen).
    const changed = (data as { keys?: unknown } | null)?.keys;
    if (Array.isArray(changed) && (changed.includes('modules.enabled') || changed.includes('*'))) {
      keys.push(qk.modules, qk.templates, qk.gallery, ['homelab']);
    }
  }
  for (const queryKey of keys) void client.invalidateQueries({ queryKey });
}

export function ServerEventsProvider(props: { children: ReactNode }): JSX.Element {
  const client = useQueryClient();
  const handlers = useRef(new Map<ServerEventName, Set<Handler>>());
  const [connected, setConnected] = useState(false);
  const [value] = useState<Omit<EventsContextValue, 'connected'>>(() => ({
    subscribe(name, handler) {
      let set = handlers.current.get(name);
      if (!set) {
        set = new Set();
        handlers.current.set(name, set);
      }
      set.add(handler);
      return () => {
        set.delete(handler);
      };
    },
  }));

  useEffect(() => {
    if (!getToken() || typeof EventSource === 'undefined') return undefined;
    let source: EventSource | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;
    let reconnecting = false;
    let wasOpen = false;
    let stopped = false;

    const dispatch = (name: ServerEventName, ev: MessageEvent) => {
      let data: unknown = null;
      try {
        data = typeof ev.data === 'string' && ev.data ? JSON.parse(ev.data) : null;
      } catch {
        data = null;
      }
      invalidateFor(client, name, data);
      for (const handler of [...(handlers.current.get(name) ?? [])]) {
        try {
          handler(data);
        } catch (err) {
          console.error(err);
        }
      }
    };

    const markOpen = () => {
      if (reconnecting) {
        // Nach einer Unterbrechung kann alles veraltet sein.
        reconnecting = false;
        void client.invalidateQueries();
      }
      attempt = 0;
      wasOpen = true;
      setConnected(true);
    };

    const connect = () => {
      if (stopped) return;
      const es = new EventSource(authUrl('/api/v1/events'));
      source = es;
      es.onopen = () => markOpen();
      for (const name of EVENT_NAMES) {
        es.addEventListener(name, (ev) => {
          if (name === 'hello') markOpen();
          dispatch(name, ev as MessageEvent);
        });
      }
      es.onerror = () => {
        es.close();
        if (source !== es || stopped) return;
        source = null;
        reconnecting = true;
        setConnected(false);
        if (wasOpen) {
          // Einmal je Abbruch: ist der Dienst weg oder mit neuem Token neu gestartet, zeigt die
          // App-Info das (ServiceGate: „nicht erreichbar“ bzw. „Sitzung abgelaufen“).
          wasOpen = false;
          void client.invalidateQueries({ queryKey: qk.app });
        }
        const delay = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)] ?? 10000;
        attempt += 1;
        timer = setTimeout(connect, delay);
      };
    };

    connect();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      source?.close();
      source = null;
    };
  }, [client]);

  return <EventsContext.Provider value={{ ...value, connected }}>{props.children}</EventsContext.Provider>;
}

export function useServerEvent<T = unknown>(name: ServerEventName, handler: (data: T) => void): void {
  const ctx = useContext(EventsContext);
  const ref = useRef(handler);
  ref.current = handler;
  const subscribe = ctx?.subscribe;
  useEffect(() => {
    if (!subscribe) return undefined;
    return subscribe(name, (data) => ref.current(data as T));
  }, [subscribe, name]);
}

export function useEventsConnected(): boolean {
  return useContext(EventsContext)?.connected ?? false;
}
