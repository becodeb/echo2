import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { AdminOrgOut, ServerAIOut, ServerAITestOut } from "../../api/types";
import { Select } from "../../components/Select";
import { Button, Card, Input, Spinner } from "../../components/ui";

/**
 * La IA de la instalación: el modelo por defecto y el de cada sede. El superadmin
 * nunca lee una key: la carga y la ve enmascarada.
 */

const LLM_PROVIDERS = ["openai", "anthropic", "gemini", "groq", "openrouter", "orcarouter", "gmi", "vercel", "deepseek", "ollama"];
const PROVIDER_OPTIONS = LLM_PROVIDERS.map((provider) => ({ value: provider, label: provider }));

/** El modelo de una sede: va dentro de su ficha en el panel. */
export function OrgAIForm({ org }: { org: AdminOrgOut }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
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
    <div className="space-y-4">
      <p className="text-sm text-ink-500">
        {org.llm_provider ? (
          <>
            Genera actas con <span className="font-medium text-ink-700">{org.llm_provider}</span>
            {org.llm_model && ` · ${org.llm_model}`}
            {org.llm_api_key_masked && ` · ${org.llm_api_key_masked}`}
          </>
        ) : (
          "No hay ningún modelo disponible: las actas de esta sede no se van a generar."
        )}
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        <Select
          label="Proveedor"
          value={form.llm_provider}
          onChange={(next) => setForm({ ...form, llm_provider: next })}
          options={[{ value: "", label: "Usar default del servidor" }, ...PROVIDER_OPTIONS]}
        />
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
        placeholder={org.uses_own_key ? "Dejar vacío para no cambiarla" : "Pegá la key del proveedor"}
        value={form.llm_api_key}
        onChange={(event) => setForm({ ...form, llm_api_key: event.target.value })}
      />
      <p className="text-xs text-ink-400">
        La key se guarda cifrada y no se puede volver a leer desde ninguna pantalla, ni siquiera acá.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={() => save.mutate()} disabled={save.isPending}>
          {save.isPending ? <Spinner /> : "Guardar"}
        </Button>
        {org.uses_own_key && (
          <Button variant="soft" onClick={() => clearKey.mutate()} disabled={clearKey.isPending}>
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
  );
}

export function ServerDefaultCard() {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ llm_provider: "", llm_model: "", llm_api_key: "" });
  const [loaded, setLoaded] = useState(false);
  const [test, setTest] = useState<ServerAITestOut | null>(null);

  const { data: defaults } = useQuery({
    queryKey: ["ai-defaults"],
    queryFn: () => api<ServerAIOut>("/api/admin/ai-defaults", { skipOrg: true }),
  });

  if (defaults && !loaded) {
    setForm({
      llm_provider: defaults.llm_provider ?? "",
      llm_model: defaults.llm_model ?? "",
      llm_api_key: "",
    });
    setLoaded(true);
  }

  const save = useMutation({
    mutationFn: () =>
      api<ServerAIOut>("/api/admin/ai-defaults", {
        method: "PUT",
        skipOrg: true,
        body: JSON.stringify({
          llm_provider: form.llm_provider,
          llm_model: form.llm_model,
          llm_api_key: form.llm_api_key === "" ? null : form.llm_api_key,
        }),
      }),
    onSuccess: () => {
      setForm((current) => ({ ...current, llm_api_key: "" }));
      setTest(null);
      queryClient.invalidateQueries({ queryKey: ["ai-defaults"] });
      queryClient.invalidateQueries({ queryKey: ["admin-orgs"] });
    },
  });

  const probe = useMutation({
    mutationFn: () =>
      api<ServerAITestOut>("/api/admin/ai-defaults/test", { method: "POST", skipOrg: true }),
    onSuccess: (result) => setTest(result),
  });

  return (
    <Card className="space-y-4">
      <div>
        <h2 className="text-[15px] font-semibold text-ink-900">Modelo por defecto</h2>
        <p className="mt-1 text-sm text-ink-500">
          Lo que usa toda organización que no configuró el suyo. Cambiarlo acá aplica al
          instante, sin reiniciar nada.
        </p>
      </div>

      {defaults?.source === "entorno" && (
        <p className="rounded-xl bg-ink-50 px-3 py-2 text-sm text-ink-600">
          Hoy sale de las variables de entorno del servidor
          {defaults.llm_provider && <> (<span className="font-medium">{defaults.llm_provider}</span>)</>}.
          Lo que cargues acá pasa a mandar.
        </p>
      )}
      {defaults?.source === "sin_configurar" && (
        <p className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700">
          No hay ningún modelo por defecto: ninguna organización sin configuración propia puede
          generar actas.
        </p>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <Select
          label="Proveedor"
          value={form.llm_provider}
          onChange={(next) => setForm({ ...form, llm_provider: next })}
          options={[{ value: "", label: "Sin default" }, ...PROVIDER_OPTIONS]}
        />
        <Input
          label="Modelo"
          placeholder="ej: Qwen/Qwen3.8-Max-0902"
          value={form.llm_model}
          onChange={(event) => setForm({ ...form, llm_model: event.target.value })}
        />
      </div>
      <Input
        label="API key"
        type="password"
        autoComplete="off"
        placeholder={
          defaults?.llm_api_key_masked
            ? `Guardada (${defaults.llm_api_key_masked}). Dejar vacío para no cambiarla`
            : "Pegá la key del proveedor"
        }
        value={form.llm_api_key}
        onChange={(event) => setForm({ ...form, llm_api_key: event.target.value })}
      />

      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={() => save.mutate()} disabled={save.isPending}>
          {save.isPending ? <Spinner /> : "Guardar"}
        </Button>
        <Button variant="soft" onClick={() => probe.mutate()} disabled={probe.isPending}>
          {probe.isPending ? <Spinner /> : "Probar ahora"}
        </Button>
        {save.isSuccess && <span className="text-sm text-emerald-600">Guardado</span>}
      </div>

      {test && (
        <div
          className={`rounded-xl px-3 py-2 text-sm ${
            test.ok ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-700"
          }`}
        >
          <span className="font-medium">
            {test.ok ? "Funciona" : "No funciona"}
            {test.provider && ` · ${test.provider}`}
            {test.model && ` · ${test.model}`}
          </span>
          <p className="mt-0.5 break-words">{test.message}</p>
        </div>
      )}
      <p className="text-xs text-ink-400">
        "Probar ahora" le pide una respuesta real al proveedor. Es la única forma de distinguir
        una key bien escrita de una que de verdad funciona: una cuenta sin saldo pasa cualquier
        validación y recién falla cuando alguien intenta generar un acta.
      </p>
    </Card>
  );
}
