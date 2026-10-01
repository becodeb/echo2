import { describe, expect, it, vi } from "vitest";
import { micErrorMessage } from "./micError";

describe("micErrorMessage", () => {
  vi.stubGlobal("navigator", { mediaDevices: { getUserMedia: () => undefined } });

  it("distingue permiso, micrófono ausente y micrófono ocupado", () => {
    expect(micErrorMessage(new DOMException("Permission denied", "NotAllowedError"))).toMatch(/permiso/);
    expect(micErrorMessage(new DOMException("Requested device not found", "NotFoundError"))).toMatch(/ningún micrófono/);
    expect(micErrorMessage(new DOMException("Could not start audio source", "NotReadableError"))).toMatch(/otra aplicación/);
  });

  it("deja pasar los errores propios de Echo y no muestra los del navegador en inglés", () => {
    expect(micErrorMessage(new Error("No se pudo conectar al servidor"))).toBe("No se pudo conectar al servidor");
    expect(micErrorMessage(new DOMException("Something odd", "UnknownError"), "No arrancó")).toBe("No arrancó");
  });
});
