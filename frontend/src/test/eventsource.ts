import { vi } from "vitest";

/** Фейк EventSource: эмит именованных событий + имитация разрыва (onerror). */
export class FakeEventSource {
  static instances: FakeEventSource[] = [];
  static last(): FakeEventSource {
    const inst = FakeEventSource.instances.at(-1);
    if (!inst) throw new Error("FakeEventSource: ни одного инстанса не создано");
    return inst;
  }
  static reset() {
    FakeEventSource.instances = [];
  }

  url: string;
  readyState = 1; // OPEN
  onerror: ((e: Event) => void) | null = null;
  private listeners = new Map<string, Set<(e: MessageEvent) => void>>();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, fn: (e: MessageEvent) => void) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)!.add(fn);
  }

  close() {
    this.readyState = 2; // CLOSED
  }

  /** Доставить именованное SSE-событие (data — объект {seq,type,payload}, сериализуется как на проводе). */
  emit(type: string, data: unknown) {
    const e = new MessageEvent(type, { data: JSON.stringify(data) });
    this.listeners.get(type)?.forEach((fn) => fn(e));
  }

  /** Имитация разрыва соединения. */
  fail() {
    this.onerror?.(new Event("error"));
  }
}

export function installFakeEventSource() {
  vi.stubGlobal("EventSource", FakeEventSource as unknown as typeof EventSource);
}
