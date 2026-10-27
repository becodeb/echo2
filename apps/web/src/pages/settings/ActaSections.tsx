import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { ReasonOut } from "../../api/types";
import { Select } from "../../components/Select";
import { Badge, Button, Input, Spinner } from "../../components/ui";
import { useAuth } from "../../state/auth";
import { ACTA_ENTREVISTA_COLEGIO } from "../../lib/actaTemplates";
import { Block, ErrorText, Loading } from "./parts";

// ── Formato de acta (con el idioma adentro) ──────────────────────

/** Idioma del acta. Los colegios no eligen modelo ni cargan keys: las pone Becode. */
function MinutesLanguage() {
  const queryClient = useQueryClient();
  const { data: settings } = useQuery({
    queryKey: ["ai-settings"],
    queryFn: () => api<{ minutes_language: string }>("/api/org/ai-settings"),
  });
  const save = useMutation({
    mutationFn: (minutes_language: string) =>
      api("/api/org/ai-settings", { method: "PUT", body: JSON.stringify({ minutes_language }) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ai-settings"] }),
  });

  return (
    <Block id="minutes-language" title="Idioma del acta" hint="Puede ser distinto del idioma que se habló en la reunión.">
      {!settings ? (
        <Spinner />
      ) : (
        <div className="flex flex-wrap items-center gap-3">
          <Select
            ariaLabel="Idioma del acta"
            value={settings.minutes_language}
            onChange={(value) => save.mutate(value)}
            options={[
              { value: "es", label: "Español" },
              { value: "en", label: "English" },
              { value: "pt", label: "Português" },
            ]}
            className="w-48"
          />
          {save.isPending && <Spinner />}
          {save.isSuccess && <span className="text-sm text-emerald-600">Guardado ✓</span>}
          {save.isError && (
            <span className="text-sm text-red-600">
              {save.error instanceof Error ? save.error.message : "No se pudo guardar"}
            </span>
          )}
        </div>
      )}
    </Block>
  );
}

export function TemplateSection() {
  const queryClient = useQueryClient();
  const { data: template } = useQuery({
    queryKey: ["minutes-template"],
    queryFn: () =>
      api<{ id: string; name: string; body_markdown: string; is_provisional: boolean }>("/api/org/minutes-template"),
  });
  const [name, setName] = useState("");
  const [body, setBody] = useState("");

  useEffect(() => {
    if (template) {
      setName(template.name);
      setBody(template.body_markdown);
    }
  }, [template]);

  const save = useMutation({
    mutationFn: () =>
      api("/api/org/minutes-template", {
        method: "PUT",
        body: JSON.stringify({ name, body_markdown: body }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["minutes-template"] }),
  });

  return (
    <div>
      <MinutesLanguage />
      <Block
        id="minutes-template"
        title={
          <span className="flex items-center gap-2">
            Modelo del acta
            {template?.is_provisional && <Badge tone="amber">Provisional</Badge>}
          </span>
        }
        hint="Pegá acá el modelo real de tu organización (estructura, títulos, tablas, firmas) y Echo lo respeta al pie de la letra."
      >
        {!template ? (
          <Loading />
        ) : (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="soft"
                onClick={() => {
                  setName("Acta de entrevista");
                  setBody(ACTA_ENTREVISTA_COLEGIO);
                }}
              >
                Cargar modelo: acta de entrevista (colegio)
              </Button>
              <span className="text-xs text-ink-400">
                Alumno, curso, solicitada por, motivo, desarrollo, acuerdos y firmas. Ajustalo y guardalo.
              </span>
            </div>
            <Input label="Nombre de la plantilla" value={name} onChange={(event) => setName(event.target.value)} />
            <textarea
              value={body}
              onChange={(event) => setBody(event.target.value)}
              rows={16}
              aria-label="Modelo del acta"
              className="w-full rounded-xl border border-ink-200 p-4 font-mono text-sm leading-relaxed focus:border-accent-500 focus:outline-none"
            />
            <div className="flex items-center gap-3">
              <Button onClick={() => save.mutate()} disabled={save.isPending}>
                {save.isPending ? <Spinner /> : "Guardar como modelo oficial"}
              </Button>
              {save.isSuccess && <span className="text-sm text-emerald-600">Guardado ✓</span>}
            </div>
          </div>
        )}
      </Block>
    </div>
  );
}

// ── Numeración de actas ──────────────────────────────────────────

interface NumberingOut {
  next_number: number;
  last_assigned: number | null;
}

export function NumberingSection() {
  const queryClient = useQueryClient();
  const { activeOrg } = useAuth();
  const isAdmin = activeOrg?.role === "owner" || activeOrg?.role === "admin";
  const [value, setValue] = useState("");

  const { data: numbering, isLoading } = useQuery({
    queryKey: ["minutes-numbering"],
    queryFn: () => api<NumberingOut>("/api/org/minutes-numbering"),
  });

  const save = useMutation({
    mutationFn: (nextNumber: number) =>
      api<NumberingOut>("/api/org/minutes-numbering", {
        method: "PUT",
        body: JSON.stringify({ next_number: nextNumber }),
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(["minutes-numbering"], data);
      setValue("");
    },
  });

  if (isLoading || !numbering) return <Loading />;

  const minimum = (numbering.last_assigned ?? 0) + 1;
  const parsed = Number(value);
  const valid = value.trim() !== "" && Number.isInteger(parsed) && parsed >= minimum;

  return (
    <div>
      <Block
        id="numbering-status"
        hint="Cada acta recibe su número cuando se genera o se imprime por primera vez, lo que pase antes. Una vez asignado no cambia, y dos actas nunca comparten número."
      >
        <div className="grid grid-cols-2 gap-3 sm:max-w-md">
          <div className="rounded-xl bg-ink-50 px-4 py-3">
            <p className="text-xs text-ink-500">Última asignada</p>
            <p className="text-xl font-semibold tabular-nums text-ink-900">
              {numbering.last_assigned != null ? `N.º ${numbering.last_assigned}` : "—"}
            </p>
          </div>
          <div className="rounded-xl bg-ink-50 px-4 py-3">
            <p className="text-xs text-ink-500">Próxima</p>
            <p className="text-xl font-semibold tabular-nums text-ink-900">N.º {numbering.next_number}</p>
          </div>
        </div>
      </Block>

      <Block
        id="numbering-start"
        title="Seguir desde un número"
        hint="Para continuar la numeración que traían de antes: si la última acta en papel fue la N.º 347, poné 348."
      >
        {isAdmin ? (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (valid) save.mutate(parsed);
            }}
            className="space-y-2"
          >
            <div className="flex flex-wrap items-end gap-2">
              <div className="w-44">
                <Input
                  label="Próximo número"
                  type="number"
                  inputMode="numeric"
                  min={minimum}
                  step={1}
                  placeholder={String(numbering.next_number)}
                  value={value}
                  onChange={(event) => setValue(event.target.value)}
                />
              </div>
              <Button type="submit" variant="soft" disabled={!valid || save.isPending}>
                {save.isPending ? <Spinner /> : "Guardar"}
              </Button>
            </div>
            {numbering.last_assigned != null && (
              <p className="text-xs text-ink-400">
                No puede ser menor a {minimum}: hasta la {minimum - 1} ya están usadas.
              </p>
            )}
            {value.trim() !== "" && !valid && (
              <p className="text-sm text-red-600">Tiene que ser un número entero desde {minimum}.</p>
            )}
            {save.isError && <ErrorText error={save.error} fallback="No se pudo guardar" />}
          </form>
        ) : (
          <p className="text-xs text-ink-400">Solo un administrador puede cambiar desde qué número sigue.</p>
        )}
      </Block>
    </div>
  );
}

// ── Motivos de reunión ───────────────────────────────────────────

export function ReasonsSection() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");

  const { data: reasons, isLoading } = useQuery({
    queryKey: ["reasons", "all"],
    queryFn: () => api<ReasonOut[]>("/api/org/meeting-reasons?include_inactive=true"),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["reasons"] });
    queryClient.invalidateQueries({ queryKey: ["reasons", "all"] });
  };

  const create = useMutation({
    mutationFn: () =>
      api<ReasonOut>("/api/org/meeting-reasons", {
        method: "POST",
        body: JSON.stringify({ name, is_active: true, position: (reasons?.length ?? 0) + 1 }),
      }),
    onSuccess: () => {
      setName("");
      invalidate();
    },
  });

  const toggle = useMutation({
    mutationFn: (reason: ReasonOut) =>
      api<ReasonOut>(`/api/org/meeting-reasons/${reason.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: reason.name,
          is_active: !reason.is_active,
          position: reason.position,
        }),
      }),
    onSuccess: invalidate,
  });

  if (isLoading) return <Loading />;

  return (
    <div>
      <Block
        id="reasons-list"
        hint="Tenerla cerrada es lo que hace que los reportes por motivo sirvan. Los motivos se desactivan en vez de borrarse: las reuniones viejas siguen mostrando con qué motivo se cargaron."
      >
        {(reasons ?? []).length > 0 ? (
          <ul className="divide-y divide-ink-100">
            {(reasons ?? []).map((reason) => (
              <li key={reason.id} className="flex items-center gap-2 py-2 text-sm">
                <span className={reason.is_active ? "text-ink-800" : "text-ink-400 line-through"}>{reason.name}</span>
                {!reason.is_active && <Badge tone="gray">Inactivo</Badge>}
                <button
                  onClick={() => toggle.mutate(reason)}
                  className="ml-auto min-h-9 px-2 text-xs text-ink-400 hover:text-ink-700"
                >
                  {reason.is_active ? "Desactivar" : "Reactivar"}
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-ink-400">Todavía no hay motivos.</p>
        )}
      </Block>

      <Block id="reasons-new" title="Agregar un motivo">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (name.trim()) create.mutate();
          }}
          className="flex flex-wrap items-end gap-2"
        >
          <div className="min-w-[200px] flex-1">
            <Input
              aria-label="Nuevo motivo"
              placeholder="ej: Seguimiento pedagógico, Conducta, Inasistencias"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <Button type="submit" variant="soft" disabled={create.isPending}>
            {create.isPending ? <Spinner /> : "Agregar"}
          </Button>
        </form>
        {create.isError && <ErrorText error={create.error} fallback="No se pudo agregar" />}
      </Block>
    </div>
  );
}
