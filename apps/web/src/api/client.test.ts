import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Los tests corren en node, sin DOM: se stubea lo mínimo que usa apiDownload
// (localStorage al importar el módulo, y el <a download> que dispara la bajada).
type FakeLink = { href: string; download: string; click: ReturnType<typeof vi.fn>; remove: () => void };

let links: FakeLink[];
let fetchMock: ReturnType<typeof vi.fn>;

function fileResponse(body: string, disposition?: string) {
  const headers = new Headers({ "content-type": "application/pdf" });
  if (disposition) headers.set("content-disposition", disposition);
  return new Response(body, { status: 200, headers });
}

async function loadClient() {
  vi.resetModules();
  return import("./client");
}

beforeEach(() => {
  links = [];
  const storage = new Map<string, string>([["echo_org", "org-123"]]);
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
    removeItem: (key: string) => storage.delete(key),
  });
  vi.stubGlobal("window", { setTimeout: () => 0, dispatchEvent: () => true });
  vi.stubGlobal("document", {
    createElement: () => {
      const link: FakeLink = { href: "", download: "", click: vi.fn(), remove: () => {} };
      links.push(link);
      return link;
    },
    body: { appendChild: () => {} },
  });
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:echo/1");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("apiDownload (exportar acta y transcript)", () => {
  it("manda el token y la organización, y baja con el nombre del servidor", async () => {
    const client = await loadClient();
    client.setAccessToken("tok-1");
    fetchMock.mockResolvedValueOnce(fileResponse("%PDF-1.4", 'attachment; filename="acta-Reunión.pdf"'));

    await client.apiDownload("/api/meetings/m1/export/minutes.pdf", "acta.pdf");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe("/api/meetings/m1/export/minutes.pdf");
    expect(init.headers).toMatchObject({ Authorization: "Bearer tok-1", "X-Organization-Id": "org-123" });
    expect(links).toHaveLength(1);
    expect(links[0].href).toBe("blob:echo/1");
    expect(links[0].download).toBe("acta-Reunión.pdf");
    expect(links[0].click).toHaveBeenCalled();
  });

  it("con el token vencido lo renueva y reintenta con el nuevo", async () => {
    const client = await loadClient();
    client.setAccessToken("vencido");
    fetchMock
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Token inválido o expirado" }), { status: 401 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ access_token: "tok-2" }), { status: 200 }))
      .mockResolvedValueOnce(fileResponse("# Transcript", 'attachment; filename="transcript-x.md"'));

    await client.apiDownload("/api/meetings/m1/export/transcript.md", "transcript.md");

    expect(fetchMock.mock.calls[1][0]).toBe("/api/auth/refresh");
    expect(fetchMock.mock.calls[2][1].headers).toMatchObject({ Authorization: "Bearer tok-2" });
    expect(links[0].download).toBe("transcript-x.md");
  });

  it("no rompe con un título que tiene %", async () => {
    const client = await loadClient();
    client.setAccessToken("tok-1");
    fetchMock.mockResolvedValueOnce(fileResponse("x", 'attachment; filename="acta-Avance-50%.md"'));

    await client.apiDownload("/api/meetings/m1/export/minutes.md", "acta.md");

    expect(links[0].download).toBe("acta-Avance-50%.md");
  });

  it("decodifica filename* y usa el nombre de respaldo si no viene ninguno", async () => {
    const client = await loadClient();
    client.setAccessToken("tok-1");
    fetchMock
      .mockResolvedValueOnce(fileResponse("x", "attachment; filename*=UTF-8''acta-%E2%80%94.docx"))
      .mockResolvedValueOnce(fileResponse("x"));

    await client.apiDownload("/api/meetings/m1/export/minutes.docx", "acta.docx");
    await client.apiDownload("/api/meetings/m1/export/minutes.docx", "acta.docx");

    expect(links.map((link) => link.download)).toEqual(["acta-—.docx", "acta.docx"]);
  });

  it("si el API rechaza, tira ApiError con el detalle y no baja nada", async () => {
    const client = await loadClient();
    client.setAccessToken("tok-1");
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Reunión no encontrada" }), { status: 404 }));

    await expect(client.apiDownload("/api/meetings/m1/export/minutes.pdf", "acta.pdf")).rejects.toMatchObject({
      status: 404,
      message: "Reunión no encontrada",
    });
    expect(links).toHaveLength(0);
  });
});
