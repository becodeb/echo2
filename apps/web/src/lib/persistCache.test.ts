import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient } from "@tanstack/react-query";

// Vitest corre en node: un localStorage mínimo y el id de build que pone Vite.
const store = new Map<string, string>();
vi.stubGlobal("localStorage", {
  getItem: (key: string) => store.get(key) ?? null,
  setItem: (key: string, value: string) => void store.set(key, value),
  removeItem: (key: string) => void store.delete(key),
});
vi.stubGlobal("window", { addEventListener: () => {}, removeEventListener: () => {} });
vi.stubGlobal("__BUILD_ID__", "build-1");

const { clearPersistedCache, persistCache, restorePersistedCache } = await import("./persistCache");

function clientWithData() {
  const client = new QueryClient();
  client.setQueryData(["dashboard", "org-1"], { recent_meetings: [{ id: "m1" }] });
  client.setQueryData(["transcript", "m1", ""], { pages: [] });
  return client;
}

describe("caché guardada", () => {
  beforeEach(() => {
    store.clear();
    vi.useFakeTimers();
  });
  afterEach(() => vi.useRealTimers());

  it("restaura lo de la misma persona y sin transcripts", async () => {
    const source = clientWithData();
    const stop = persistCache(source, "user-a");
    source.setQueryData(["dashboard", "org-1"], { recent_meetings: [{ id: "m2" }] });
    await vi.advanceTimersByTimeAsync(2100);
    stop();

    const target = new QueryClient();
    expect(restorePersistedCache(target, "user-a")).toBe(true);
    expect(target.getQueryData(["dashboard", "org-1"])).toEqual({ recent_meetings: [{ id: "m2" }] });
    expect(target.getQueryData(["transcript", "m1", ""])).toBeUndefined();
  });

  it("no restaura lo de otra persona y lo borra", async () => {
    const source = clientWithData();
    const stop = persistCache(source, "user-a");
    source.setQueryData(["dashboard", "org-1"], { recent_meetings: [] });
    await vi.advanceTimersByTimeAsync(2100);
    stop();

    expect(restorePersistedCache(new QueryClient(), "user-b")).toBe(false);
    expect(store.size).toBe(0);
  });

  it("no restaura lo de otra versión de la app ni lo vencido", () => {
    store.set("echo_cache", JSON.stringify({ user: "user-a", build: "build-0", at: Date.now(), state: { queries: [], mutations: [] } }));
    expect(restorePersistedCache(new QueryClient(), "user-a")).toBe(false);
    store.set("echo_cache", JSON.stringify({ user: "user-a", build: "build-1", at: Date.now() - 25 * 3600_000, state: { queries: [], mutations: [] } }));
    expect(restorePersistedCache(new QueryClient(), "user-a")).toBe(false);
  });

  it("cerrar sesión la borra", () => {
    store.set("echo_cache", "{}");
    clearPersistedCache();
    expect(store.has("echo_cache")).toBe(false);
  });
});
