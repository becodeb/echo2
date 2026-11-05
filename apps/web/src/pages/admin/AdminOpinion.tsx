import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { FeedbackCard, type FeedbackKind } from "../../components/FeedbackPrompt";
import { timeAgo } from "../../components/NotificationsPanel";
import { Switch } from "../../components/Toggles";
import { Button, Card, EmptyState, Input, Spinner } from "../../components/ui";
import { Chip } from "../settings/Positions";

/**
 * Lo que opina la gente: el promedio de estrellitas, las sugerencias y cómo se
 * pregunta. Los popups arrancan apagados: se prenden acá.
 */

interface PromptConfig {
  kind: FeedbackKind;
  enabled: boolean;
  title: string;
  question: string;
  every_days: number;
}

interface ResponseRow {
  id: string;
  kind: FeedbackKind;
  stars: number | null;
  text: string | null;
  created_at: string;
  user_name: string;
  user_email: string;
  organization: string | null;
}

interface Overview {
  prompts: PromptConfig[];
  distribution: number[];
  average: number | null;
  suggestions: number;
  dismissed: number;
  responses: ResponseRow[];
}

const PROMPT_NAME: Record<FeedbackKind, { name: string; hint: string }> = {
  stars: { name: "Estrellitas", hint: "De 1 a 5, con un comentario si quiere." },
  suggestion: { name: "Sugerencias", hint: "Una pregunta abierta para que escriba." },
};

type Filter = "all" | "stars" | "suggestion" | "low";

function StarsLine({ value, label }: { value: number; label?: string }) {
  return (
    <span role="img" aria-label={label ?? `${value} de 5 estrellas`} className="inline-flex">
      {[1, 2, 3, 4, 5].map((star) => (
        <svg key={star} width="15" height="15" viewBox="0 0 24 24" aria-hidden className={star <= Math.round(value) ? "text-amber-400" : "text-ink-200"}>
          <path fill="currentColor" d="M12 3.6l2.5 5.2 5.7.8-4.1 4 1 5.7-5.1-2.7-5.1 2.7 1-5.7-4.1-4 5.7-.8z" />
        </svg>
      ))}
    </span>
  );
}

function Summary({ data }: { data: Overview }) {
  const total = data.distribution.reduce((sum, count) => sum + count, 0);
  const top = Math.max(1, ...data.distribution);
  return (
    <div className="grid gap-5 rounded-3xl border border-ink-100 bg-white p-5 shadow-[0_1px_2px_rgba(16,24,40,0.03)] sm:grid-cols-[auto_1fr] sm:gap-8 sm:p-6">
      <div>
        <p className="text-5xl font-semibold tracking-tight tabular-nums text-ink-900">
          {data.average != null ? data.average.toLocaleString("es") : "—"}
        </p>
        <div className="mt-1.5">
          <StarsLine value={data.average ?? 0} label={data.average != null ? `Promedio: ${data.average} de 5` : "Sin puntajes todavía"} />
        </div>
        <p className="mt-1 text-xs text-ink-400">
          {total === 1 ? "1 puntaje" : `${total} puntajes`} · {data.suggestions === 1 ? "1 sugerencia" : `${data.suggestions} sugerencias`}
        </p>
        <p className="text-xs text-ink-400">{data.dismissed === 1 ? "1 «Ahora no»" : `${data.dismissed} «Ahora no»`}</p>
      </div>
      <ul className="space-y-1.5 self-center" aria-label="Cuántas respuestas hay de cada puntaje">
        {[5, 4, 3, 2, 1].map((stars) => {
          const count = data.distribution[stars - 1];
          return (
            <li key={stars} className="flex items-center gap-2.5 text-xs text-ink-500" title={`${stars} estrellas: ${count}`}>
              <span className="w-3 text-right tabular-nums">{stars}</span>
              <span className="h-2 flex-1 overflow-hidden rounded-full bg-ink-100">
                <span
                  className="block h-full rounded-full bg-accent-500 transition-[width] duration-500"
                  style={{ width: `${(count / top) * 100}%`, minWidth: count ? 8 : 0 }}
                />
              </span>
              <span className="w-7 tabular-nums">{count}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function PromptEditor({ prompt, onPreview }: { prompt: PromptConfig; onPreview: () => void }) {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState(prompt.title);
  const [question, setQuestion] = useState(prompt.question);
  const [days, setDays] = useState(String(prompt.every_days));
  const save = useMutation({
    mutationFn: (body: Partial<PromptConfig>) =>
      api(`/api/admin/feedback/prompts/${prompt.kind}`, { method: "PUT", skipOrg: true, body: JSON.stringify(body) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-feedback"] }),
  });
  const dayCount = Number(days);
  const validDays = Number.isInteger(dayCount) && dayCount >= 7 && dayCount <= 365;
  const dirty = title.trim() !== prompt.title || question.trim() !== prompt.question || dayCount !== prompt.every_days;
  const meta = PROMPT_NAME[prompt.kind];
  return (
    <section className="space-y-3 rounded-3xl border border-ink-100 bg-white p-5 shadow-[0_1px_2px_rgba(16,24,40,0.03)]">
      <Switch
        checked={prompt.enabled}
        onChange={(enabled) => save.mutate({ enabled })}
        label={meta.name}
        hint={prompt.enabled ? `${meta.hint} Prendido: le aparece a la gente.` : `${meta.hint} Apagado: no le aparece a nadie.`}
      />
      <Input label="Título" value={title} maxLength={120} onChange={(event) => setTitle(event.target.value)} />
      <Input label="Pregunta" value={question} maxLength={300} onChange={(event) => setQuestion(event.target.value)} />
      <Input
        label="Volver a preguntarle a la misma persona cada (días)"
        type="number"
        min={7}
        max={365}
        value={days}
        onChange={(event) => setDays(event.target.value)}
      />
      {!validDays && <p className="text-xs text-amber-700">Entre 7 y 365 días.</p>}
      {save.isError && <p className="text-sm text-red-600">{save.error instanceof Error ? save.error.message : "No se pudo guardar"}</p>}
      <div className="flex flex-wrap gap-2">
        <Button
          onClick={() => save.mutate({ title: title.trim(), question: question.trim(), every_days: dayCount })}
          disabled={!dirty || !validDays || !title.trim() || !question.trim() || save.isPending}
        >
          {save.isPending ? <Spinner /> : "Guardar"}
        </Button>
        <Button variant="soft" onClick={onPreview}>Ver cómo se ve</Button>
      </div>
    </section>
  );
}

function ResponseItem({ row }: { row: ResponseRow }) {
  return (
    <li className="px-5 py-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {row.stars != null ? (
          <StarsLine value={row.stars} />
        ) : (
          <span className="text-xs font-medium text-accent-700">Sugerencia</span>
        )}
        <span className="text-xs text-ink-400">{timeAgo(row.created_at)}</span>
      </div>
      {row.text && <p className="mt-1.5 whitespace-pre-wrap text-sm leading-relaxed text-ink-800">{row.text}</p>}
      <p className="mt-1.5 truncate text-xs text-ink-400">
        {row.user_name} · {row.user_email}
        {row.organization && ` · ${row.organization}`}
      </p>
    </li>
  );
}

export function AdminOpinion() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["admin-feedback"],
    queryFn: () => api<Overview>("/api/admin/feedback", { skipOrg: true }),
  });
  const [filter, setFilter] = useState<Filter>("all");
  const [preview, setPreview] = useState<PromptConfig | null>(null);

  if (isLoading) {
    return (
      <div className="flex justify-center py-16 text-ink-300">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }
  if (isError || !data) {
    return (
      <Card>
        <EmptyState title="No se pudo cargar" mood="error">
          <p>{error instanceof Error ? error.message : "Probá de nuevo en un momento."}</p>
        </EmptyState>
      </Card>
    );
  }

  const rows = data.responses.filter((row) => {
    if (filter === "stars") return row.stars != null;
    if (filter === "suggestion") return row.kind === "suggestion";
    if (filter === "low") return row.stars != null && row.stars <= 2;
    return true;
  });
  const anyOn = data.prompts.some((prompt) => prompt.enabled);

  return (
    <div className="space-y-6">
      <Summary data={data} />

      <div className="grid gap-4 lg:grid-cols-2">
        {data.prompts.map((prompt) => (
          <PromptEditor
            key={`${prompt.kind}-${prompt.title}-${prompt.question}-${prompt.every_days}`}
            prompt={prompt}
            onPreview={() => setPreview(prompt)}
          />
        ))}
      </div>
      <p className="text-xs leading-relaxed text-ink-400">
        Sale como una tarjeta abajo a la derecha, a los 20 segundos de entrar. No aparece durante una reunión en vivo ni a
        cuentas de menos de 3 días, y nunca dos preguntas a la misma persona en menos de una semana.
      </p>

      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-[15px] font-semibold text-ink-900">Lo que respondieron</h2>
          <div role="group" aria-label="Filtrar respuestas" className="flex flex-wrap gap-1.5">
            <Chip active={filter === "all"} onClick={() => setFilter("all")}>Todas</Chip>
            <Chip active={filter === "stars"} onClick={() => setFilter("stars")}>Con estrellas</Chip>
            <Chip active={filter === "low"} onClick={() => setFilter("low")}>1 o 2 estrellas</Chip>
            <Chip active={filter === "suggestion"} onClick={() => setFilter("suggestion")}>Sugerencias</Chip>
          </div>
        </div>
        {rows.length === 0 ? (
          <Card>
            <EmptyState title={data.responses.length ? "Ninguna con ese filtro" : "Todavía no respondió nadie"} mood="idle">
              {!data.responses.length && !anyOn && <p>Prendé una de las preguntas de arriba para empezar.</p>}
            </EmptyState>
          </Card>
        ) : (
          <ul className="divide-y divide-ink-100 rounded-3xl border border-ink-100 bg-white shadow-[0_1px_2px_rgba(16,24,40,0.03)]">
            {rows.map((row) => (
              <ResponseItem key={row.id} row={row} />
            ))}
          </ul>
        )}
      </section>

      {preview && (
        <FeedbackCard
          key={preview.kind}
          prompt={preview}
          // Es una muestra: no se guarda nada.
          onSend={() => undefined}
          onLater={() => setPreview(null)}
          onClose={() => setPreview(null)}
        />
      )}
    </div>
  );
}
