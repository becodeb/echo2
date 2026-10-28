import { useEffect, useState, type ChangeEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { ActaLevel, LetterheadOut, LevelLetterhead } from "../../api/types";
import { Select } from "../../components/Select";
import { Button, Input, Spinner } from "../../components/ui";
import { Block, Loading } from "./parts";

const LEVELS: { key: ActaLevel; label: string }[] = [
  { key: "inicial", label: "Inicial" },
  { key: "primaria", label: "Primaria" },
  { key: "secundaria", label: "Secundaria" },
];

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
  // Lo que se tipea en el encabezado de cada nivel (los renglones vacíos se descartan al guardar).
  const [levelLinesText, setLevelLinesText] = useState<Record<string, string>>({});
  const [logoError, setLogoError] = useState<string | null>(null);

  useEffect(() => {
    if (data) {
      setForm(data);
      setLinesText(data.lines.join("\n"));
      setSignaturesText(data.signatures.join("\n"));
      setLevelLinesText({});
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

  if (!form) return <Loading />;

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
    <div>
      <Block id="letterhead-logo" title="Logo" hint="Se usa tal cual en el acta impresa, sin pasar por la IA.">
        <div className="flex items-start gap-4">
          <div className="flex h-20 w-32 shrink-0 items-center justify-center rounded-xl border border-dashed border-ink-200 bg-ink-50">
            {form.logo_data_url ? (
              <img src={form.logo_data_url} alt="Logo" className="max-h-16 max-w-[7rem] object-contain" />
            ) : (
              <span className="text-xs text-ink-400">Sin logo</span>
            )}
          </div>
          <div className="space-y-2">
            <label className="inline-flex cursor-pointer items-center rounded-xl bg-ink-100 px-3.5 py-2 text-sm font-medium text-ink-800 hover:bg-ink-200">
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
      </Block>

      <Block id="letterhead-header" title="Encabezado y datos">
        <div className="space-y-4">
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-ink-700">Encabezado (una línea por renglón)</span>
            <textarea
              value={linesText}
              onChange={(event) => setLinesText(event.target.value)}
              rows={4}
              placeholder={"Dirección General de Cultura y Educación\nRegión 11\nDistrito Escobar"}
              className="w-full rounded-xl border border-ink-200 px-3 py-2 text-sm leading-relaxed focus:border-accent-500 focus:outline-none"
            />
          </label>
  
          <Input label="Institución" value={form.institution} onChange={set("institution")} />
          <Input label="Dirección" value={form.address} onChange={set("address")} placeholder="Calle 123, Ciudad" />
          <div className="grid gap-4 sm:grid-cols-2">
            <Input label="Teléfono" value={form.phone} onChange={set("phone")} />
            <Input label="Email" value={form.email} onChange={set("email")} />
          </div>
          <Input label="Título del acta" value={form.title} onChange={set("title")} placeholder="Acta de entrevista" />
          <Select
            label="Fuente del acta"
            value={form.font ?? "arial"}
            onChange={(font) => setForm({ ...form, font: font as LetterheadOut["font"] })}
            options={[
              { value: "arial", label: "Arial (sans serif)" },
              { value: "calibri", label: "Calibri (sans serif)" },
              { value: "times", label: "Times New Roman (con serif)" },
              { value: "trebuchet", label: "Trebuchet MS (sans serif)" },
            ]}
          />
          <p className="-mt-2 text-xs text-ink-400">Se usa en el acta impresa, en Word y en PDF.</p>
          <Input
            label="Lugar en el acta de entrevista"
            value={form.interview_place}
            onChange={set("interview_place")}
            placeholder="la institución educativa de nivel primario denominada …, registro de DIEGEP Nº …"
          />
          <p className="-mt-2 text-xs text-ink-400">
            Completa el párrafo del formulario: «A los … días del mes de … en las instalaciones de <em>esto</em>, se reúnen…».
          </p>
        </div>
      </Block>

      <Block
        id="letterhead-levels"
        title="Formulario y colegio por nivel"
        hint="Cada nivel puede usar su formulario y nombrar al colegio a su manera. Si no cargás nada, sale como hasta ahora."
      >
        <div className="space-y-5">
          {LEVELS.map(({ key, label }) => {
            const level = form.levels?.[key] ?? { format: "", school: "", lines: [] };
            const setLevel = (patch: Partial<LevelLetterhead>) =>
              setForm({ ...form, levels: { ...form.levels, [key]: { ...level, ...patch } } });
            return (
              <div key={key} className="space-y-3 rounded-2xl border border-ink-100 p-4">
                <h4 className="text-sm font-semibold text-ink-900">{label}</h4>
                <Select
                  label="Formulario"
                  value={level.format}
                  onChange={(format) => setLevel({ format: format as LevelLetterhead["format"] })}
                  options={[
                    { value: "", label: "El del modelo de acta de la sede" },
                    { value: "entrevista", label: "Acta de entrevista (con casilleros)" },
                    { value: "reunion", label: "Acta de reunión (en prosa)" },
                  ]}
                />
                <Input
                  label="Cómo se nombra al colegio"
                  value={level.school}
                  onChange={(event) => setLevel({ school: event.target.value })}
                  placeholder={
                    level.format === "reunion"
                      ? "la sede del Colegio … (sigue a «en»)"
                      : "del Colegio … registro de DIEGEP N° … de nivel …"
                  }
                />
                <label className="block">
                  <span className="mb-1.5 block text-sm font-medium text-ink-700">
                    Encabezado de este nivel (una línea por renglón)
                  </span>
                  <textarea
                    value={levelLinesText[key] ?? level.lines.join("\n")}
                    onChange={(event) => {
                      setLevelLinesText({ ...levelLinesText, [key]: event.target.value });
                      setLevel({ lines: event.target.value.split("\n").map((line) => line.trim()).filter(Boolean) });
                    }}
                    rows={3}
                    placeholder="Vacío: se usa el encabezado de arriba"
                    className="w-full rounded-xl border border-ink-200 px-3 py-2 text-sm leading-relaxed focus:border-accent-500 focus:outline-none"
                  />
                </label>
                <p className="-mt-1 text-xs text-ink-400">
                  {level.format === "reunion"
                    ? "Reemplaza al lugar de arriba: «A los … días … en esto, siendo las …»."
                    : "Con esto el acta de entrevista sale como la planilla: «A los … días del mes de …, se reúnen … esto con: …»."}
                </p>
              </div>
            );
          })}
        </div>
      </Block>

      <Block id="letterhead-signatures" title="Firmas al pie" hint="Una por renglón.">
        <textarea
          value={signaturesText}
          onChange={(event) => setSignaturesText(event.target.value)}
          rows={3}
          aria-label="Firmas al pie"
          placeholder={"Firma docente\nFirma familia"}
          className="w-full rounded-xl border border-ink-200 px-3 py-2 text-sm leading-relaxed focus:border-accent-500 focus:outline-none"
        />
      </Block>

      {/* Un solo Guardar para todo el membrete, siempre a la vista. -bottom-10 y
          pb-14: se pega al borde de la ventana, tapando el margen de abajo. */}
      <div className="sticky -bottom-10 -mb-10 flex items-center gap-3 border-t border-ink-100 bg-white pb-14 pt-3">
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
  );
}
