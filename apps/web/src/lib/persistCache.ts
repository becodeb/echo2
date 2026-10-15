import { dehydrate, hydrate, type QueryClient } from "@tanstack/react-query";

/**
 * Lo último que se vio (inicio, listas, reuniones abiertas) queda guardado en
 * este navegador: al volver a entrar se muestra al instante y se actualiza de
 * fondo, en vez de esperar al servidor con la pantalla vacía.
 *
 * - Solo para la misma persona: se restaura recién cuando el servidor confirma
 *   la sesión y es el mismo usuario; si es otro, se borra.
 * - Al cerrar sesión se borra.
 * - Vence a las 24 h y con cada versión nueva de la app (las formas cambian).
 * - Sin transcripts ni chats: son lo más pesado y se piden al abrir.
 */
const STORAGE_KEY = "echo_cache";
const MAX_AGE_MS = 24 * 60 * 60 * 1000;
const MAX_BYTES = 1_500_000;
// my-access, internal-groups y billing deciden qué se dibuja: sin ellos la app espera al servidor igual.
// Son solo para la pantalla (los permisos los valida el servidor) y se revalidan al entrar.
const KEEP = new Set([
  "dashboard", "meetings", "meeting", "summary", "insights", "minutes", "tasks", "my-voice", "notifications",
  "my-access", "internal-groups", "billing",
]);

interface Stored {
  user: string;
  build: string;
  at: number;
  state: ReturnType<typeof dehydrate>;
}

function read(): Stored | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Stored) : null;
  } catch {
    return null;
  }
}

export function clearPersistedCache(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* sin almacenamiento */
  }
}

/** Restaura lo guardado si es de esta persona y está vigente. Devuelve si restauró. */
export function restorePersistedCache(queryClient: QueryClient, userId: string): boolean {
  const stored = read();
  if (!stored) return false;
  if (stored.user !== userId || stored.build !== __BUILD_ID__ || Date.now() - stored.at > MAX_AGE_MS) {
    clearPersistedCache();
    return false;
  }
  hydrate(queryClient, stored.state);
  return true;
}

/** Guarda la caché cada vez que cambia (como mucho cada 2 s) y al irse de la página. */
export function persistCache(queryClient: QueryClient, userId: string): () => void {
  let timer: ReturnType<typeof setTimeout> | null = null;
  const save = () => {
    timer = null;
    const state = dehydrate(queryClient, {
      shouldDehydrateQuery: (query) => query.state.status === "success" && KEEP.has(String(query.queryKey[0])),
    });
    const payload = JSON.stringify({ user: userId, build: __BUILD_ID__, at: Date.now(), state } satisfies Stored);
    try {
      if (payload.length > MAX_BYTES) clearPersistedCache();
      else localStorage.setItem(STORAGE_KEY, payload);
    } catch {
      /* lleno o bloqueado: no pasa nada, solo no se guarda */
    }
  };
  const schedule = () => {
    if (!timer) timer = setTimeout(save, 2000);
  };
  const unsubscribe = queryClient.getQueryCache().subscribe((event) => {
    if (event.type === "updated" && event.action.type === "success") schedule();
  });
  const onHide = () => save();
  window.addEventListener("pagehide", onHide);
  return () => {
    unsubscribe();
    window.removeEventListener("pagehide", onHide);
    if (timer) clearTimeout(timer);
  };
}
