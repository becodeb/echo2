import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { FamilyOut } from "../api/types";
import { Select } from "./Select";
import { Button, Input, Spinner } from "./ui";

/**
 * Desplegable de familias con búsqueda y alta en el lugar.
 *
 * "Nueva familia" abre un formulario corto debajo del desplegable, no un
 * modal: así sirve igual dentro de otro modal (el de nueva reunión). Al crear,
 * la familia queda elegida.
 */
export function FamilySelect({
  value,
  onChange,
  label = "Familia",
  enabled = true,
}: {
  value: string;
  onChange: (familyId: string) => void;
  label?: string;
  /** Para no pedir la lista hasta que el formulario esté a la vista. */
  enabled?: boolean;
}) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<{ name: string; reference: string } | null>(null);

  const { data: families } = useQuery({
    queryKey: ["families"],
    queryFn: () => api<FamilyOut[]>("/api/families"),
    enabled,
  });

  // Se agrega a la caché en el acto para que el nombre y los integrantes
  // aparezcan sin esperar la recarga de la lista.
  const create = useMutation({
    mutationFn: (form: { name: string; reference: string }) =>
      api<FamilyOut>("/api/families", {
        method: "POST",
        body: JSON.stringify({ name: form.name.trim(), reference: form.reference.trim() || null }),
      }),
    onSuccess: (family) => {
      queryClient.setQueryData<FamilyOut[]>(["families"], (current) => [...(current ?? []), family]);
      queryClient.invalidateQueries({ queryKey: ["families"] });
      onChange(family.id);
      setDraft(null);
    },
  });

  const submit = () => {
    if (draft?.name.trim()) create.mutate(draft);
  };

  return (
    <div className="space-y-2">
      <Select
        label={label}
        value={value}
        onChange={onChange}
        options={[
          { value: "", label: "Sin familia" },
          ...(families ?? []).map((family) => ({
            value: family.id,
            label: family.name,
            hint: family.reference ? `Legajo ${family.reference}` : undefined,
          })),
        ]}
        placeholder={families ? "Sin familia" : "Cargando…"}
        searchable
        searchPlaceholder="Buscar por apellido o legajo…"
        action={{
          label: "Nueva familia",
          // Lo buscado suele ser el apellido: se propone "Familia <apellido>".
          onClick: (query) =>
            setDraft({
              name: !query || /^familia\b/i.test(query) ? query : `Familia ${query[0].toUpperCase()}${query.slice(1)}`,
              reference: "",
            }),
        }}
      />

      {draft && (
        // Un div y no un <form>: puede quedar dentro del formulario de otra
        // cosa, y un form anidado mandaría el de afuera con el Enter.
        <div
          className="animate-fade-up space-y-3 rounded-lg border border-ink-100 bg-ink-50 p-3"
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              submit();
            } else if (event.key === "Escape") {
              event.stopPropagation();
              setDraft(null);
            }
          }}
        >
          <p className="text-sm font-medium text-ink-800">Nueva familia</p>
          <div className="grid gap-2 sm:grid-cols-[1fr_10rem]">
            <Input
              placeholder="Familia Gómez"
              aria-label="Nombre de la familia"
              autoFocus
              value={draft.name}
              onChange={(event) => setDraft({ ...draft, name: event.target.value })}
            />
            <Input
              placeholder="Legajo (opcional)"
              aria-label="Legajo o matrícula"
              value={draft.reference}
              onChange={(event) => setDraft({ ...draft, reference: event.target.value })}
            />
          </div>
          {create.isError && (
            <p className="text-sm text-red-600">
              {create.error instanceof Error ? create.error.message : "No se pudo crear"}
            </p>
          )}
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs text-ink-400">Los integrantes se cargan después en Familias.</p>
            <div className="flex shrink-0 gap-2">
              <Button type="button" variant="ghost" onClick={() => setDraft(null)}>
                Cancelar
              </Button>
              <Button type="button" onClick={submit} disabled={!draft.name.trim() || create.isPending}>
                {create.isPending ? <Spinner /> : "Crear"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
