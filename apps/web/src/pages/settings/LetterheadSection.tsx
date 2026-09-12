import { useEffect, useState, type ChangeEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { LetterheadOut } from "../../api/types";
import { Button, Card, Input, Spinner } from "../../components/ui";

const LOGO_MAX_BYTES = 400 * 1024;

/**
 * Membrete del acta impresa: líneas de encabezado (organismo, región,
 * distrito), logo, institución, dirección, contacto, título y firmas. Lo ve
 * la hoja de impresión; el generador de actas no lo toca.
 */
export function LetterheadSection() {
  const queryClient = useQueryClient();
  const { data } = useQuery({
    queryKey: ["letterhead"],
    queryFn: () => api<LetterheadOut>("/api/org/letterhead"),
  });

  const [form, setForm] = useState<LetterheadOut | null>(null);
  const [linesText, setLinesText] = useState("");
  const [signaturesText, setSignaturesText] = useState("");
  const [logoError, setLogoError] = useState<string | null>(null);

  useEffect(() => {
    if (data) {
      setForm(data);
      setLinesText(data.lines.join("\n"));
      setSignaturesText(data.signatures.join("\n"));
    }
  }, [data]);

  const save = useMutation({
    mutationFn: () =>
      api<LetterheadOut>("/api/org/letterhead", {
        method: "PUT",
        body: JSON.stringify({
          ...form,
          lines: linesText.split("\n").map((line) => line.trim()).filter(Boolean),
          signatures: signaturesText.split("\n").map((line) => line.trim()).filter(Boolean),
        }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["letterhead"] }),
  });

  if (!form) return <div className="flex justify-center py-10 text-ink-300"><Spinner /></div>;

  const set = (field: keyof LetterheadOut) => (event: ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [field]: event.target.value });

  const onLogo = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setLogoError(null);
    if (!/^image\/(png|jpeg|webp|svg\+xml)$/.test(file.type)) {
      setLogoError("El logo tiene que ser PNG, JPG, WebP o SVG.");
      return;
    }
    if (file.size > LOGO_MAX_BYTES) {
      setLogoError("El logo pesa más de 400 KB. Achicalo y volvé a probar.");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => setForm({ ...form, logo_data_url: String(reader.result) });
    reader.readAsDataURL(file);
  };

  return (
    <Card>
      <h2 className="mb-1 font-semibold text-ink-900">Membrete</h2>
      <p className="mb-5 text-sm text-ink-400">
        Lo que va arriba del acta impresa: encabezado institucional, logo, dirección y firmas. Se
        usa tal cual, sin pasar por la IA.
      </p>

      <div className="space-y-4">
        <div className="flex items-start gap-4">
          <div className="flex h-20 w-32 shrink-0 items-center justify-center rounded-lg border border-dashed border-ink-200 bg-ink-50">
            {form.logo_data_url ? (
              <img src={form.logo_data_url} alt="Logo" className="max-h-16 max-w-[7rem] object-contain" />
            ) : (
              <span className="text-xs text-ink-400">Sin logo</span>
            )}
          </div>
          <div className="space-y-2">
            <label className="inline-flex cursor-pointer items-center rounded-lg bg-ink-100 px-3.5 py-2 text-sm font-medium text-ink-800 hover:bg-ink-200">
              {form.logo_data_url ? "Cambiar logo" : "Subir logo"}
              <input type="file" accept="image/png,image/jpeg,image/webp,image/svg+xml" className="hidden" onChange={onLogo} />
            </label>
            {form.logo_data_url && (
              <Button variant="ghost" onClick={() => setForm({ ...form, logo_data_url: null })}>
                Quitar logo
              </Button>
            )}
            <p className="text-xs text-ink-400">PNG, JPG, WebP o SVG. Hasta 400 KB.</p>
            {logoError && <p className="text-xs text-red-600">{logoError}</p>}
          </div>
        </div>

        <label className="block">
          <span className="mb-1.5 block text-sm font-medium text-ink-700">Encabezado (una línea por renglón)</span>
          <textarea
            value={linesText}
            onChange={(event) => setLinesText(event.target.value)}
            rows={4}
            placeholder={"Dirección General de Cultura y Educación\nRegión 11\nDistrito Escobar"}
            className="w-full rounded-lg border border-ink-200 px-3 py-2 text-sm leading-relaxed focus:border-accent-500 focus:outline-none"
          />
        </label>

        <Input label="Institución" value={form.institution} onChange={set("institution")} />
        <Input label="Dirección" value={form.address} onChange={set("address")} placeholder="Calle 123, Ciudad" />
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="Teléfono" value={form.phone} onChange={set("phone")} />
          <Input label="Email" value={form.email} onChange={set("email")} />
        </div>
        <Input label="Título del acta" value={form.title} onChange={set("title")} placeholder="Acta de entrevista" />

        <label className="block">
          <span className="mb-1.5 block text-sm font-medium text-ink-700">Firmas al pie (una por renglón)</span>
          <textarea
            value={signaturesText}
            onChange={(event) => setSignaturesText(event.target.value)}
            rows={3}
            placeholder={"Firma docente\nFirma familia"}
            className="w-full rounded-lg border border-ink-200 px-3 py-2 text-sm leading-relaxed focus:border-accent-500 focus:outline-none"
          />
        </label>

        <div className="flex items-center gap-3">
          <Button onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending ? <Spinner /> : "Guardar membrete"}
          </Button>
          {save.isSuccess && <span className="text-sm text-emerald-600">Guardado ✓</span>}
          {save.isError && (
            <span className="text-sm text-red-600">
              {save.error instanceof Error ? save.error.message : "No se pudo guardar"}
            </span>
          )}
        </div>
      </div>
    </Card>
  );
}
