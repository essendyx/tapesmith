type Listener = (ev: MessageEvent) => void;

/** Ersatz für EventSource in Tests: Ereignisse per `emit` auslösen. */
export class FakeEventSource {
  static instances: FakeEventSource[] = [];
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;

  url: string;
  readyState = FakeEventSource.CONNECTING;
  withCredentials = false;
  onopen: ((ev: Event) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  onmessage: Listener | null = null;
  private listeners = new Map<string, Set<Listener>>();

  constructor(url: string | URL) {
    this.url = String(url);
    FakeEventSource.instances.push(this);
  }

  static reset(): void {
    FakeEventSource.instances = [];
  }

  static latest(): FakeEventSource | undefined {
    return FakeEventSource.instances[FakeEventSource.instances.length - 1];
  }

  addEventListener(name: string, fn: Listener): void {
    let set = this.listeners.get(name);
    if (!set) {
      set = new Set();
      this.listeners.set(name, set);
    }
    set.add(fn);
  }

  removeEventListener(name: string, fn: Listener): void {
    this.listeners.get(name)?.delete(fn);
  }

  /** Verbindung als geöffnet melden. */
  open(): void {
    this.readyState = FakeEventSource.OPEN;
    this.onopen?.(new Event('open'));
  }

  /** Verbindungsfehler simulieren (der Provider verbindet dann neu). */
  fail(): void {
    this.readyState = FakeEventSource.CLOSED;
    this.onerror?.(new Event('error'));
  }

  emit(name: string, data: unknown): void {
    if (this.readyState === FakeEventSource.CLOSED) return;
    if (this.readyState !== FakeEventSource.OPEN) this.open();
    const ev = new MessageEvent(name, { data: JSON.stringify(data) });
    if (name === 'message') this.onmessage?.(ev);
    for (const fn of this.listeners.get(name) ?? []) fn(ev);
  }

  close(): void {
    this.readyState = FakeEventSource.CLOSED;
  }
}
