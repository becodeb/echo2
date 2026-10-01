/**
 * Qué pasó con el micrófono, en palabras de quien lo usa. El navegador da el
 * motivo en inglés ("Permission denied", "Requested device not found"); acá se
 * traduce según el tipo de error, así no se dice "falta permiso" cuando el
 * problema es que no hay micrófono o que otra aplicación lo está usando.
 */
export function micErrorMessage(error: unknown, fallback = "No se pudo usar el micrófono."): string {
  if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
    return "Este navegador no deja usar el micrófono acá. Probá desde Chrome o Safari actualizados.";
  }
  const name = error instanceof DOMException || error instanceof Error ? error.name : "";
  if (name === "NotAllowedError" || name === "SecurityError" || name === "PermissionDeniedError") {
    return "Echo necesita permiso para usar el micrófono. Habilitalo en el candado de la barra de direcciones.";
  }
  if (name === "NotFoundError" || name === "OverconstrainedError" || name === "DevicesNotFoundError") {
    return "No encontramos ningún micrófono conectado.";
  }
  if (name === "NotReadableError" || name === "AbortError" || name === "TrackStartError") {
    return "El micrófono lo está usando otra aplicación. Cerrala y probá de nuevo.";
  }
  if (error instanceof DOMException) return fallback;
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}
