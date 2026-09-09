import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { AdminOrgOut } from "../api/types";
import { Badge, Button, Card, EmptyState, Input, Spinner } from "../components/ui";

/**
 * Panel de superadmin: todas las organizaciones de la instalación y la IA de
 * cada una.
 *
 * Es transversal, así que las llamadas van con skipOrg: no hay organización
 * activa que aplique acá, y el superadmin no es miembro de las que administra.
 */

const LLM_PROVIDERS = ["openai", "anthropic", "gemini", "groq", "openrouter", "gmi", "ollama"];

interface AIForm {
  llm_provider: string;
  llm_model: string;
  llm_api_key: string;
}

function OrgRow({ org }: { org: AdminOrgOut }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<AIForm>({
    llm_provider: org.uses_own_key ? org.llm_provider ?? "" : "",
    llm_model: org.uses_own_key ? org.llm_model ?? "" : "",
    llm_api_key: "",
  });

  const save = useMutation({
    mutationFn: () =>
      api<AdminOrgOut>(`/api/admin/organizations/${org.id}/ai`, {
        method: "PUT",
        skipOrg: true,
        body: JSON.stringify({
          llm_provider: form.llm_provider,
          llm_model: form.llm_model,
          // Vacío = no tocar la key que ya está guardada.
          llm_api_key: form.llm_api_key === "" ? null : form.llm_api_key,
        }),
      }),
    onSuccess: () => {
      setForm((current) => ({ ...current, llm_api_key: "" }));
      queryClient.invalidateQueries({ queryKey: ["admin-orgs"] });
    },
  });

  const clearKey = useMutation({
    mutationFn: () =>
      api<AdminOrgOut>(`/api/admin/organizations/${org.id}/ai`, {
        method: "PUT",
        skipOrg: true,
        body: JSON.stringify({ llm_provider: "", llm_model: "", llm_api_key: "" }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-orgs"] }),
  });

  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-[15px] font-semibold text-ink-900">{org.name}</h3>
          <p className="mt-0.5 text-sm text-ink-500">
            {org.members} {org.members === 1 ? "miembro" : "miembros"} · {org.meetings}{" "}
            {org.meetings === 1 ? "reunión" : "reuniones"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {org.uses_own_key ? (
            <Badge tone="green">Key propia</Badge>
          ) : org.llm_provider ? (
            <Badge tone="amber">Usa el default del servidor</Badge>
          ) : (
            <Badge tone="red">Sin IA</Badge>
          )}
          <Button variant="soft" onClick={() => setOpen((value) => !value)}>
            {open ? "Cerrar" : "Configurar IA"}
          </Button>
        </div>
      </div>

      <p className="text-sm text-ink-500">
        {org.llm_provider ? (
          <>
            Genera actas con <span className="font-medium text-ink-700">{org.llm_provider}</span>
            {org.llm_model && ` · ${org.llm_model}`}
            {org.llm_api_key_masked && ` · ${org.llm_api_key_masked}`}
          </>
        ) : (
          "No hay ningún modelo disponible: las actas de esta organización no se van a generar."
        )}
      </p>

      {open && (
        <div className="space-y-4 border-t border-ink-100 pt-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-ink-700">Proveedor</span>
              <select
                value={form.llm_provider}
                onChange={(event) =>
                  setForm({ ...form, llm_provider: event.target.value })
                }
                className="w-full rounded-lg border border-ink-200 px-3 py-2 text-sm"
              >
                <option value="">— usar default del servidor —</option>
                {LLM_PROVIDERS.map((provider) => (
                  <option key={provider} value={provider}>
                    {provider}
                  </option>
                ))}
              </select>
            </label>
            <Input
              label="Modelo"
              placeholder="ej: gpt-4o-mini, anthropic/claude-sonnet-4.5"
              value={form.llm_model}
              onChange={(event) => setForm({ ...form, llm_model: event.target.value })}
            />
          </div>
          <Input
            label="API key"
            type="password"
            autoComplete="off"
            placeholder={
              org.uses_own_key ? "Dejar vacío para no cambiarla" : "Pegá la key del proveedor"
            }
            value={form.llm_api_key}
            onChange={(event) => setForm({ ...form, llm_api_key: event.target.value })}
          />
          <p className="text-xs text-ink-400">
            La key se guarda cifrada y no se puede volver a leer desde ninguna pantalla, ni
            siquiera acá.
          </p>

          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={() => save.mutate()} disabled={save.isPending}>
              {save.isPending ? <Spinner /> : "Guardar"}
            </Button>
            {org.uses_own_key && (
              <Button
                variant="soft"
                onClick={() => clearKey.mutate()}
                disabled={clearKey.isPending}
              >
                Quitar key y volver al default
              </Button>
            )}
            {save.isSuccess && <span className="text-sm text-emerald-600">Guardado</span>}
            {save.isError && (
              <span className="text-sm text-red-600">
                {save.error instanceof Error ? save.error.message : "No se pudo guardar"}
              </span>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}

export default function Admin() {
  const { data: orgs, isLoading, isError, error } = useQuery({
    queryKey: ["admin-orgs"],
    queryFn: () => api<AdminOrgOut[]>("/api/admin/organizations", { skipOrg: true }),
  });

  if (isLoading) {
    return (
      <div className="flex justify-center py-16 text-ink-300">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }

  if (isError) {
    return (
      <Card>
        <EmptyState title="No se pudo cargar el panel" mood="error">
          <p>{error instanceof Error ? error.message : "Probá de nuevo en un momento."}</p>
        </EmptyState>
      </Card>
    );
  }

  const sinIA = (orgs ?? []).filter((org) => !org.llm_provider).length;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-ink-900">Organizaciones</h1>
        <p className="mt-1 text-sm text-ink-500">
          Todas las organizaciones de esta instalación y el modelo de IA que usa cada una.
        </p>
      </div>

      {sinIA > 0 && (
        <div className="rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-800">
          {sinIA === 1
            ? "Hay 1 organización sin ningún modelo de IA disponible: sus actas no se van a generar."
            : `Hay ${sinIA} organizaciones sin ningún modelo de IA disponible: sus actas no se van a generar.`}
        </div>
      )}

      {(orgs ?? []).length === 0 ? (
        <Card>
          <EmptyState title="Todavía no hay organizaciones" mood="idle">
            <p>Cuando alguien cree la primera, va a aparecer acá.</p>
          </EmptyState>
        </Card>
      ) : (
        <div className="space-y-3">
          {(orgs ?? []).map((org) => (
            <OrgRow key={org.id} org={org} />
          ))}
        </div>
      )}
    </div>
  );
}
