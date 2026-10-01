/**
 * Adónde volver después de entrar (§4.13): el link que se quería abrir sin
 * sesión. Para el login con Google (que sale de la página) queda guardado en
 * sessionStorage.
 */
const KEY = "echo_next";

export function safeNext(value: string | null | undefined): string | null {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.startsWith("/login")) return null;
  return value;
}

export function rememberNext(value: string | null | undefined): void {
  const next = safeNext(value);
  try {
    if (next) sessionStorage.setItem(KEY, next);
  } catch {
    // Sin almacenamiento: se vuelve al inicio, nada más.
  }
}

export function takeNext(): string | null {
  try {
    const next = safeNext(sessionStorage.getItem(KEY));
    sessionStorage.removeItem(KEY);
    return next;
  } catch {
    return null;
  }
}
