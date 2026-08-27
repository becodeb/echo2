import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ChatOut, InsightsOut, MeetingOut, MinutesOut, SegmentOut } from "../api/types";
import { Badge, Button, Card, EmptyState, Input, Modal, Spinner, formatDate, formatDuration, formatMs } from "../components/ui";
import { EchoFace } from "../components/EchoFace";

const TABS = [
  { id: "summary", label: "Resumen" },
  { id: "transcript", label: "Transcript" },
  { id: "minutes", label: "Acta" },
  { id: "tasks", label: "Tareas" },
  { id: "chat", label: "Chat" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export default function MeetingDetail() {
  const { id } = useParams<{ id: string }>();
  const [params, setParams] = useSearchParams();
  const [tab, setTab] = useState<TabId>((params.get("tab") as TabId) || "summary");
  const jumpMs = params.get("t");

  const { data: meeting, refetch } = useQuery({
    queryKey: ["meeting", id],
    queryFn: () => api<MeetingOut>(`/api/meetings/${id}`),
    enabled: !!id,
    refetchInterval: (query) => (query.state.data?.status === "processing" ? 3000 : false),
  });

  useEffect(() => {
    if (jumpMs != null) setTab("transcript");
  }, [jumpMs]);

  if (!meeting) {
    return (
      <div className="flex h-full items-center justify-center text-ink-300">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }

  const skipped = (meeting.processing_state?.skipped as string[] | undefined) ?? [];
  const aiSkipped = skipped.some((entry) => entry.includes("llm_no_configurado"));

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <header className="mb-6">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold tracking-tight text-ink-900">{meeting.title}</h1>
          {meeting.status === "processing" && (
            <Badge tone="sky">
              <Spinner className="h-3 w-3" /> Procesando
            </Badge>
          )}
          {meeting.status === "failed" && <Badge tone="red">Falló</Badge>}
          <div className="ml-auto">
            <ShareButton meetingId={meeting.id} />
          </div>
        </div>
        <p className="mt-1 text-sm text-ink-500">
          {formatDate(meeting.started_at)} · {formatDuration(meeting.duration_seconds)}
          {meeting.participants.length > 0 &&
            ` · ${meeting.participants.map((participant) => participant.name).join(", ")}`}
        </p>
        {aiSkipped && (
          <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-700">
            El análisis con IA se salteó porque no hay un modelo configurado.{" "}
            <Link to="/settings/ai" className="font-medium underline">Configurar IA</Link>
          </p>
        )}
      </header>

      <nav className="mb-6 flex gap-1 border-b border-ink-100" role="tablist">
        {TABS.map((item) => (
          <button
            key={item.id}
            role="tab"
            aria-selected={tab === item.id}
            onClick={() => {
              setTab(item.id);
              params.set("tab", item.id);
              setParams(params, { replace: true });
            }}
            className={`border-b-2 px-4 py-2.5 text-sm font-medium transition-colors ${
              tab === item.id
                ? "border-ink-900 text-ink-900"
                : "border-transparent text-ink-400 hover:text-ink-700"
            }`}
          >
            {item.label}
          </button>
        ))}
      </nav>

      {tab === "summary" && <SummaryTab meeting={meeting} onJump={(ms) => { params.set("t", String(ms)); setParams(params); }} />}
      {tab === "transcript" && <TranscriptTab meeting={meeting} jumpMs={jumpMs ? Number(jumpMs) : null} onRefetch={refetch} />}
      {tab === "minutes" && <MinutesTab meetingId={meeting.id} />}
      {tab === "tasks" && <TasksTab meetingId={meeting.id} />}
      {tab === "chat" && <ChatTab meetingId={meeting.id} onJump={(ms) => { params.set("t", String(ms)); setParams(params); setTab("transcript"); }} />}
    </div>
  );
}

// ── Resumen ──────────────────────────────────────────────────────

function SummaryTab({ meeting, onJump }: { meeting: MeetingOut; onJump: (ms: number) => void }) {
  const { data: summaries } = useQuery({
    queryKey: ["summary", meeting.id],
    queryFn: () =>
      api<Record<string, { content: { points?: string[]; markdown?: string } }>>(
        `/api/meetings/${meeting.id}/summary`,
      ),
  });
  const { data: insights } = useQuery({
    queryKey: ["insights", meeting.id],
    queryFn: () => api<InsightsOut>(`/api/meetings/${meeting.id}/insights`),
  });

  const timeline = meeting.meta?.timeline ?? [];
  const nextSteps = meeting.meta?.next_steps ?? [];

  const empty = !summaries?.executive && !insights?.decisions.length && !timeline.length;

  return (
    <div className="space-y-6">
      {empty && (
        <Card>
          <EmptyState mood={meeting.status === "processing" ? "thinking" : "idle"} title={
            meeting.status === "processing" ? "Echo está procesando la reunión…" : "Sin análisis disponible"
          }>
            {meeting.status !== "processing" &&
              "Cuando finalices una reunión con IA configurada, acá aparecen el resumen, decisiones y tareas."}
          </EmptyState>
        </Card>
      )}

      {summaries?.executive?.content.points && (
        <Card>
          <h2 className="mb-3 font-semibold text-ink-900">Resumen ejecutivo</h2>
          <ul className="space-y-2">
            {summaries.executive.content.points.map((point, index) => (
              <li key={index} className="flex gap-2.5 text-[15px] leading-relaxed text-ink-800">
                <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-accent-500" />
                {point}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {insights && insights.decisions.length > 0 && (
        <Card>
          <h2 className="mb-3 font-semibold text-ink-900">Decisiones</h2>
          <ul className="divide-y divide-ink-100">
            {insights.decisions.map((decision) => (
              <li key={decision.id} className="py-2.5">
                <p className="text-[15px] text-ink-800">{decision.text}</p>
                <div className="mt-1 flex items-center gap-3 text-xs text-ink-400">
                  {decision.context && <span>{decision.context}</span>}
                  {decision.evidence_start_ms != null && (
                    <button
                      onClick={() => onJump(decision.evidence_start_ms!)}
                      className="font-mono text-accent-600 hover:underline"
                    >
                      Fuente: {formatMs(decision.evidence_start_ms)}
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {insights && insights.questions.length > 0 && (
        <Card>
          <h2 className="mb-3 font-semibold text-ink-900">Preguntas abiertas</h2>
          <ul className="space-y-2">
            {insights.questions.map((question) => (
              <li key={question.id} className="flex items-baseline gap-2 text-[15px] text-ink-800">
                <span className="text-ink-300">?</span>
                {question.text}
                {question.evidence_start_ms != null && (
                  <button
                    onClick={() => onJump(question.evidence_start_ms!)}
                    className="font-mono text-xs text-accent-600 hover:underline"
                  >
                    {formatMs(question.evidence_start_ms)}
                  </button>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {timeline.length > 0 && (
        <Card>
          <h2 className="mb-3 font-semibold text-ink-900">Momentos importantes</h2>
          <ol className="space-y-1.5">
            {timeline.map((moment, index) => (
              <li key={index}>
                <button
                  onClick={() => onJump(moment.at_ms)}
                  className="group flex items-baseline gap-3 text-left"
                >
                  <span className="font-mono text-xs tabular-nums text-accent-600 group-hover:underline">
                    {formatMs(moment.at_ms)}
                  </span>
                  <span className="text-[15px] text-ink-800">{moment.label}</span>
                </button>
              </li>
            ))}
          </ol>
        </Card>
      )}

      {nextSteps.length > 0 && (
        <Card>
          <h2 className="mb-3 font-semibold text-ink-900">Próximos pasos</h2>
          <ul className="space-y-1.5">
            {nextSteps.map((step, index) => (
              <li key={index} className="flex gap-2.5 text-[15px] text-ink-800">
                <span className="text-ink-300">→</span>
                {step}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {summaries?.detailed?.content.markdown && (
        <Card>
          <h2 className="mb-3 font-semibold text-ink-900">Resumen detallado</h2>
          <MarkdownView markdown={summaries.detailed.content.markdown} />
        </Card>
      )}
    </div>
  );
}

// ── Transcript ───────────────────────────────────────────────────

function TranscriptTab({
  meeting,
  jumpMs,
  onRefetch,
}: {
  meeting: MeetingOut;
  jumpMs: number | null;
  onRefetch: () => void;
}) {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [pages, setPages] = useState<SegmentOut[]>([]);
  const [nextAfter, setNextAfter] = useState<number | null>(0);
  const [editing, setEditing] = useState<SegmentOut | null>(null);
  const [editText, setEditText] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);
  const lowConfidence = pages.filter((segment) => segment.confidence != null && segment.confidence < 0.5).length;

  const speakerById = useMemo(() => {
    const map = new Map<string, { name: string; color: string }>();
    for (const speaker of meeting.speakers) {
      map.set(speaker.id, { name: speaker.display_name || speaker.label, color: speaker.color });
    }
    return map;
  }, [meeting.speakers]);

  const load = async (after: number, replace = false) => {
    const query = new URLSearchParams({ after_seq: String(after), limit: "300" });
    if (search.trim()) query.set("search", search.trim());
    const page = await api<{ segments: SegmentOut[]; next_after: number | null }>(
      `/api/meetings/${meeting.id}/transcript?${query}`,
    );
    setPages((current) => (replace ? page.segments : [...current, ...page.segments]));
    setNextAfter(page.next_after);
  };

  useEffect(() => {
    load(0, true).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meeting.id, search]);

  useEffect(() => {
    if (jumpMs == null || pages.length === 0) return;
    const target = pages.find((segment) => segment.start_ms >= jumpMs - 500);
    if (target) {
      document.getElementById(`seg-${target.id}`)?.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, [jumpMs, pages]);

  const saveEdit = useMutation({
    mutationFn: () =>
      api<SegmentOut>(`/api/meetings/${meeting.id}/transcript/${editing!.id}`, {
        method: "PATCH",
        body: JSON.stringify({ text: editText }),
      }),
    onSuccess: (updated) => {
      setPages((current) => current.map((segment) => (segment.id === updated.id ? updated : segment)));
      setEditing(null);
    },
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Buscar en el transcript…"
          className="w-64 rounded-lg border border-ink-200 px-3 py-1.5 text-sm focus:border-accent-500 focus:outline-none"
        />
        {lowConfidence > 0 && (
          <Badge tone="amber">{lowConfidence} fragmentos podrían necesitar revisión</Badge>
        )}
        <div className="ml-auto flex gap-2">
          <a
            href={`/api/meetings/${meeting.id}/export/transcript.md`}
            className="text-xs font-medium text-accent-600 hover:underline"
          >
            Exportar .md
          </a>
        </div>
      </div>

      <SpeakerEditor meeting={meeting} onChanged={onRefetch} />

      <div ref={containerRef} className="space-y-4">
        {pages.map((segment) => {
          const speaker = segment.speaker_id ? speakerById.get(segment.speaker_id) : null;
          const highlighted = jumpMs != null && Math.abs(segment.start_ms - jumpMs) < 1500;
          return (
            <div
              key={segment.id}
              id={`seg-${segment.id}`}
              className={`group rounded-lg px-3 py-2 transition-colors ${highlighted ? "bg-accent-500/10" : "hover:bg-ink-50"}`}
            >
              <div className="mb-0.5 flex items-baseline gap-2 text-xs">
                <span className="font-mono tabular-nums text-ink-400">{formatMs(segment.start_ms)}</span>
                {speaker && (
                  <span className="font-semibold" style={{ color: speaker.color }}>
                    {speaker.name}
                  </span>
                )}
                {segment.edited && <span className="text-ink-300">(editado)</span>}
                {segment.confidence != null && segment.confidence < 0.5 && (
                  <span className="text-amber-500" title="Baja confianza">~</span>
                )}
                <button
                  onClick={() => {
                    setEditing(segment);
                    setEditText(segment.text);
                  }}
                  className="invisible ml-auto text-ink-400 hover:text-ink-700 group-hover:visible"
                >
                  Editar
                </button>
              </div>
              <p className="text-[15px] leading-relaxed text-ink-900">{segment.text}</p>
            </div>
          );
        })}
        {pages.length === 0 && (
          <EmptyState title={search ? "Sin coincidencias" : "Sin transcript"} mood="idle" />
        )}
        {nextAfter != null && pages.length > 0 && (
          <div className="flex justify-center py-2">
            <Button variant="soft" onClick={() => load(nextAfter)}>Cargar más</Button>
          </div>
        )}
      </div>

      <Modal open={!!editing} onClose={() => setEditing(null)} title="Editar fragmento" wide>
        <div className="space-y-4">
          <textarea
            value={editText}
            onChange={(event) => setEditText(event.target.value)}
            rows={4}
            className="w-full rounded-lg border border-ink-200 px-3 py-2 text-sm focus:border-accent-500 focus:outline-none"
          />
          <p className="text-xs text-ink-400">
            La versión original se conserva en el historial del fragmento.
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setEditing(null)}>Cancelar</Button>
            <Button onClick={() => saveEdit.mutate()} disabled={saveEdit.isPending}>
              {saveEdit.isPending ? <Spinner /> : "Guardar"}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}

function SpeakerEditor({ meeting, onChanged }: { meeting: MeetingOut; onChanged: () => void }) {
  const [renaming, setRenaming] = useState<string | null>(null);
  const [name, setName] = useState("");

  if (meeting.speakers.length === 0) return null;

  const rename = async (speakerId: string) => {
    await api(`/api/meetings/${meeting.id}/speakers/${speakerId}`, {
      method: "PATCH",
      body: JSON.stringify({ display_name: name }),
    });
    setRenaming(null);
    onChanged();
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs font-medium text-ink-400">Hablantes:</span>
      {meeting.speakers.map((speaker) => (
        <span key={speaker.id}>
          {renaming === speaker.id ? (
            <form
              className="inline-flex items-center gap-1"
              onSubmit={(event) => {
                event.preventDefault();
                rename(speaker.id);
              }}
            >
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                autoFocus
                className="w-28 rounded border border-ink-200 px-2 py-0.5 text-xs"
              />
              <button type="submit" className="text-xs text-accent-600">OK</button>
            </form>
          ) : (
            <button
              onClick={() => {
                setRenaming(speaker.id);
                setName(speaker.display_name || "");
              }}
              className="inline-flex items-center gap-1.5 rounded-full border border-ink-200 px-2.5 py-1 text-xs font-medium text-ink-700 hover:border-ink-300"
              title="Renombrar hablante"
            >
              <span className="h-2 w-2 rounded-full" style={{ backgroundColor: speaker.color }} />
              {speaker.display_name || speaker.label}
              {speaker.identity_suggestion?.person_name && !speaker.display_name && (
                <span className="text-ink-400">
                  ¿{speaker.identity_suggestion.person_name}?{" "}
                  {Math.round((speaker.identity_suggestion.confidence ?? 0) * 100)}%
                </span>
              )}
            </button>
          )}
        </span>
      ))}
    </div>
  );
}

// ── Acta ─────────────────────────────────────────────────────────

function MinutesTab({ meetingId }: { meetingId: string }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  const { data: minutes, isLoading } = useQuery({
    queryKey: ["minutes", meetingId],
    queryFn: () => api<MinutesOut | null>(`/api/meetings/${meetingId}/minutes`),
  });

  const regenerate = useMutation({
    mutationFn: () => api(`/api/meetings/${meetingId}/minutes/generate`, { method: "POST" }),
  });

  const saveEdit = useMutation({
    mutationFn: () =>
      api(`/api/meetings/${meetingId}/minutes/versions`, {
        method: "POST",
        body: JSON.stringify({ body_markdown: draft }),
      }),
    onSuccess: () => {
      setEditing(false);
      queryClient.invalidateQueries({ queryKey: ["minutes", meetingId] });
    },
  });

  const changeStatus = useMutation({
    mutationFn: (status: string) =>
      api(`/api/meetings/${meetingId}/minutes/status`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["minutes", meetingId] }),
  });

  if (isLoading) {
    return <div className="flex justify-center py-16 text-ink-300"><Spinner className="h-6 w-6" /></div>;
  }

  if (!minutes || !minutes.version) {
    return (
      <Card>
        <EmptyState title="Todavía no hay acta" mood="idle">
          <p className="mb-4">
            El acta se genera automáticamente al finalizar la reunión (requiere IA configurada).
          </p>
          <Button onClick={() => regenerate.mutate()} disabled={regenerate.isPending}>
            {regenerate.isPending ? <Spinner /> : "Generar acta ahora"}
          </Button>
          {regenerate.isError && (
            <p className="mt-2 text-sm text-red-600">
              {regenerate.error instanceof Error ? regenerate.error.message : "Error"}
            </p>
          )}
          {regenerate.isSuccess && (
            <p className="mt-2 text-sm text-emerald-600">Generando… recargá en unos segundos.</p>
          )}
        </EmptyState>
      </Card>
    );
  }

  const statusBadge = {
    draft: <Badge tone="gray">Borrador</Badge>,
    in_review: <Badge tone="amber">En revisión</Badge>,
    approved: <Badge tone="green">Aprobada</Badge>,
  }[minutes.status];

  const verification = minutes.version.verification ?? [];
  const weak = verification.filter((claim) => claim.status !== "verified");

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {statusBadge}
        <span className="text-xs text-ink-400">
          v{minutes.version.version} · {minutes.version.note}
          {minutes.version.model_used && ` · ${minutes.version.model_used}`}
        </span>
        <div className="ml-auto flex flex-wrap gap-2">
          {!editing && (
            <>
              <Button variant="soft" onClick={() => { setDraft(minutes.version!.body_markdown); setEditing(true); }}>
                Editar
              </Button>
              {minutes.status !== "approved" && (
                <Button variant="soft" onClick={() => changeStatus.mutate(minutes.status === "draft" ? "in_review" : "approved")}>
                  {minutes.status === "draft" ? "Enviar a revisión" : "Aprobar"}
                </Button>
              )}
              <Button variant="soft" onClick={() => regenerate.mutate()} disabled={regenerate.isPending}>
                Regenerar
              </Button>
              <a href={`/api/meetings/${meetingId}/export/minutes.pdf`}>
                <Button variant="ghost">PDF</Button>
              </a>
              <a href={`/api/meetings/${meetingId}/export/minutes.docx`}>
                <Button variant="ghost">DOCX</Button>
              </a>
              <a href={`/api/meetings/${meetingId}/export/minutes.md`}>
                <Button variant="ghost">MD</Button>
              </a>
            </>
          )}
        </div>
      </div>

      {weak.length > 0 && !editing && (
        <Card className="border-amber-200 bg-amber-50/50">
          <h3 className="mb-2 text-sm font-semibold text-amber-800">
            Verificación: {weak.length} {weak.length === 1 ? "afirmación necesita" : "afirmaciones necesitan"} revisión
          </h3>
          <ul className="space-y-1.5 text-sm">
            {verification.map((claim, index) => (
              <li key={index} className="flex items-start gap-2">
                <span>{claim.status === "verified" ? "✓" : claim.status === "weak" ? "⚠" : "✗"}</span>
                <span className={claim.status === "verified" ? "text-emerald-800" : "text-amber-800"}>
                  {claim.claim}
                  {claim.evidence_ms != null && (
                    <span className="ml-2 font-mono text-xs">{formatMs(claim.evidence_ms)}</span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {editing ? (
        <Card>
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            rows={24}
            className="w-full rounded-lg border border-ink-200 p-4 font-mono text-sm leading-relaxed focus:border-accent-500 focus:outline-none"
          />
          <div className="mt-3 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setEditing(false)}>Cancelar</Button>
            <Button onClick={() => saveEdit.mutate()} disabled={saveEdit.isPending}>
              {saveEdit.isPending ? <Spinner /> : "Guardar nueva versión"}
            </Button>
          </div>
        </Card>
      ) : (
        <Card>
          <MarkdownView markdown={minutes.version.body_markdown} />
        </Card>
      )}

      {minutes.versions.length > 1 && (
        <details className="text-sm text-ink-500">
          <summary className="cursor-pointer font-medium">Historial de versiones</summary>
          <ul className="mt-2 space-y-1">
            {minutes.versions.map((version) => (
              <li key={version.version}>
                v{version.version} — {version.note} —{" "}
                {new Date(version.created_at).toLocaleString("es")}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

// ── Tareas ───────────────────────────────────────────────────────

function TasksTab({ meetingId }: { meetingId: string }) {
  const queryClient = useQueryClient();
  const { data: insights } = useQuery({
    queryKey: ["insights", meetingId],
    queryFn: () => api<InsightsOut>(`/api/meetings/${meetingId}/insights`),
  });

  const update = useMutation({
    mutationFn: ({ taskId, status }: { taskId: string; status: string }) =>
      api(`/api/tasks/${taskId}`, { method: "PATCH", body: JSON.stringify({ status }) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["insights", meetingId] }),
  });

  const tasks = insights?.action_items ?? [];
  if (tasks.length === 0) {
    return (
      <Card>
        <EmptyState title="Sin tareas detectadas" mood="idle" />
      </Card>
    );
  }

  return (
    <Card className="overflow-x-auto p-0">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-ink-100 text-left text-xs uppercase tracking-wide text-ink-400">
            <th className="px-5 py-3 font-medium">Tarea</th>
            <th className="px-3 py-3 font-medium">Responsable</th>
            <th className="px-3 py-3 font-medium">Fecha</th>
            <th className="px-3 py-3 font-medium">Estado</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-ink-100">
          {tasks.map((task) => (
            <tr key={task.id}>
              <td className="px-5 py-3 text-ink-800">{task.text}</td>
              <td className="px-3 py-3 text-ink-600">{task.assignee_name ?? "—"}</td>
              <td className="px-3 py-3 text-ink-600">
                {task.due_date ?? task.due_text ?? "—"}
              </td>
              <td className="px-3 py-3">
                <select
                  value={task.status}
                  onChange={(event) => update.mutate({ taskId: task.id, status: event.target.value })}
                  className="rounded-lg border border-ink-200 px-2 py-1 text-xs"
                >
                  <option value="pending">Pendiente</option>
                  <option value="in_progress">En progreso</option>
                  <option value="done">Completada</option>
                  <option value="cancelled">Cancelada</option>
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

// ── Chat ─────────────────────────────────────────────────────────

function ChatTab({ meetingId, onJump }: { meetingId: string; onJump: (ms: number) => void }) {
  const [messages, setMessages] = useState<{ role: "user" | "assistant"; content: string; sources?: ChatOut["sources"] }[]>([]);
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  const ask = useMutation({
    mutationFn: (question: string) =>
      api<ChatOut>(`/api/meetings/${meetingId}/chat`, {
        method: "POST",
        body: JSON.stringify({
          question,
          history: messages.slice(-6).map(({ role, content }) => ({ role, content })),
        }),
      }),
    onSuccess: (response) => {
      setMessages((current) => [...current, { role: "assistant", content: response.answer, sources: response.sources }]);
    },
    onError: (error) => {
      setMessages((current) => [
        ...current,
        { role: "assistant", content: error instanceof Error ? error.message : "Error" },
      ]);
    },
  });

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, ask.isPending]);

  const send = () => {
    const question = input.trim();
    if (!question || ask.isPending) return;
    setMessages((current) => [...current, { role: "user", content: question }]);
    setInput("");
    ask.mutate(question);
  };

  return (
    <Card className="flex h-[60vh] flex-col p-0">
      <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto p-5">
        {messages.length === 0 && (
          <EmptyState title="Preguntale a esta reunión" mood="idle">
            «¿Qué decidió Ana sobre el presupuesto?» · «¿Quién llama al proveedor?» · «¿Qué quedó pendiente?»
          </EmptyState>
        )}
        {messages.map((message, index) => (
          <div key={index} className={message.role === "user" ? "flex justify-end" : "flex justify-start"}>
            <div
              className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-[15px] leading-relaxed ${
                message.role === "user" ? "bg-ink-900 text-white" : "bg-ink-50 text-ink-900"
              }`}
            >
              <p className="whitespace-pre-wrap">{message.content}</p>
              {message.sources && message.sources.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5 border-t border-ink-200/60 pt-2">
                  {message.sources.map((source, sourceIndex) => (
                    <button
                      key={sourceIndex}
                      onClick={() => onJump(source.start_ms)}
                      className="rounded-full bg-white px-2 py-0.5 font-mono text-[11px] text-accent-600 shadow-sm hover:underline"
                      title={source.text}
                    >
                      {formatMs(source.start_ms)}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
        {ask.isPending && (
          <div className="flex items-center gap-2 text-ink-400">
            <EchoFace mood="thinking" size={26} />
            <span className="text-sm">Echo está buscando en la reunión…</span>
          </div>
        )}
      </div>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          send();
        }}
        className="flex gap-2 border-t border-ink-100 p-3"
      >
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Preguntá algo sobre esta reunión…"
          className="flex-1 rounded-xl border border-ink-200 px-4 py-2.5 text-sm focus:border-accent-500 focus:outline-none"
        />
        <Button type="submit" disabled={ask.isPending || !input.trim()}>Enviar</Button>
      </form>
    </Card>
  );
}

// ── Compartir ────────────────────────────────────────────────────

function ShareButton({ meetingId }: { meetingId: string }) {
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();
  const { data: shares } = useQuery({
    queryKey: ["shares", meetingId],
    queryFn: () =>
      api<{
        visibility: string;
        users: { id: string; user_id: string; name: string; role: string }[];
        links: { id: string; token: string; role: string; expires_at: string | null }[];
      }>(`/api/meetings/${meetingId}/shares`),
    enabled: open,
  });
  const { data: members } = useQuery({
    queryKey: ["members"],
    queryFn: () => api<{ user_id: string; name: string }[]>("/api/org/members"),
    enabled: open,
  });
  const [selectedUser, setSelectedUser] = useState("");
  const [selectedRole, setSelectedRole] = useState("viewer");
  const [copied, setCopied] = useState<string | null>(null);

  const shareUser = useMutation({
    mutationFn: () =>
      api(`/api/meetings/${meetingId}/shares`, {
        method: "POST",
        body: JSON.stringify({ user_id: selectedUser, role: selectedRole }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["shares", meetingId] }),
  });

  const createLink = useMutation({
    mutationFn: () =>
      api<{ token: string }>(`/api/meetings/${meetingId}/share-links`, {
        method: "POST",
        body: JSON.stringify({ role: "viewer", expires_days: 30 }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["shares", meetingId] }),
  });

  const revokeLink = useMutation({
    mutationFn: (linkId: string) =>
      api(`/api/meetings/${meetingId}/share-links/${linkId}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["shares", meetingId] }),
  });

  return (
    <>
      <Button variant="soft" onClick={() => setOpen(true)}>Compartir</Button>
      <Modal open={open} onClose={() => setOpen(false)} title="Compartir reunión">
        <div className="space-y-5">
          <div>
            <h3 className="mb-2 text-sm font-medium text-ink-700">Personas específicas</h3>
            <div className="flex gap-2">
              <select
                value={selectedUser}
                onChange={(event) => setSelectedUser(event.target.value)}
                className="flex-1 rounded-lg border border-ink-200 px-3 py-2 text-sm"
              >
                <option value="">Elegir persona…</option>
                {members?.map((member) => (
                  <option key={member.user_id} value={member.user_id}>{member.name}</option>
                ))}
              </select>
              <select
                value={selectedRole}
                onChange={(event) => setSelectedRole(event.target.value)}
                className="rounded-lg border border-ink-200 px-2 py-2 text-sm"
              >
                <option value="viewer">Viewer</option>
                <option value="commenter">Commenter</option>
                <option value="editor">Editor</option>
                <option value="admin">Admin</option>
              </select>
              <Button onClick={() => shareUser.mutate()} disabled={!selectedUser || shareUser.isPending}>
                Agregar
              </Button>
            </div>
            {shares && shares.users.length > 0 && (
              <ul className="mt-2 space-y-1 text-sm text-ink-600">
                {shares.users.map((share) => (
                  <li key={share.id}>{share.name} — {share.role}</li>
                ))}
              </ul>
            )}
          </div>

          <div>
            <h3 className="mb-2 text-sm font-medium text-ink-700">Link para compartir</h3>
            {shares?.links.map((link) => {
              const url = `${location.origin}/s/${link.token}`;
              return (
                <div key={link.id} className="mb-2 flex items-center gap-2">
                  <input readOnly value={url} className="min-w-0 flex-1 rounded-lg border border-ink-200 bg-ink-50 px-3 py-1.5 text-xs text-ink-600" />
                  <Button
                    variant="soft"
                    onClick={() => {
                      navigator.clipboard.writeText(url);
                      setCopied(link.id);
                      setTimeout(() => setCopied(null), 1500);
                    }}
                  >
                    {copied === link.id ? "Copiado" : "Copiar"}
                  </Button>
                  <Button variant="ghost" onClick={() => revokeLink.mutate(link.id)}>Revocar</Button>
                </div>
              );
            })}
            <Button variant="soft" onClick={() => createLink.mutate()} disabled={createLink.isPending}>
              {createLink.isPending ? <Spinner /> : "Crear link (expira en 30 días)"}
            </Button>
          </div>
        </div>
      </Modal>
    </>
  );
}

// ── Markdown renderer minimalista (sin dependencias) ─────────────

export function MarkdownView({ markdown }: { markdown: string }) {
  const html = useMemo(() => renderMarkdown(markdown), [markdown]);
  return (
    <div
      className="prose-echo max-w-none text-[15px] leading-relaxed text-ink-800 [&_h1]:mb-3 [&_h1]:text-xl [&_h1]:font-semibold [&_h2]:mb-2 [&_h2]:mt-5 [&_h2]:text-lg [&_h2]:font-semibold [&_h3]:mt-4 [&_h3]:font-semibold [&_li]:my-0.5 [&_p]:my-2 [&_table]:my-3 [&_table]:w-full [&_table]:border-collapse [&_td]:border [&_td]:border-ink-200 [&_td]:px-2.5 [&_td]:py-1.5 [&_th]:border [&_th]:border-ink-200 [&_th]:bg-ink-50 [&_th]:px-2.5 [&_th]:py-1.5 [&_th]:text-left [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5 [&_blockquote]:border-l-2 [&_blockquote]:border-ink-200 [&_blockquote]:pl-3 [&_blockquote]:text-ink-500 [&_hr]:my-4 [&_hr]:border-ink-100"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

function escapeHtml(text: string): string {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function inline(text: string): string {
  return escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|\s)_(.+?)_(?=\s|$)/g, "$1<em>$2</em>")
    .replace(/`(.+?)`/g, "<code>$1</code>");
}

function renderMarkdown(markdown: string): string {
  const lines = markdown.split("\n");
  const output: string[] = [];
  let inList = false;
  let inQuote = false;
  let tableRows: string[][] = [];

  const closeList = () => {
    if (inList) {
      output.push("</ul>");
      inList = false;
    }
  };
  const closeQuote = () => {
    if (inQuote) {
      output.push("</blockquote>");
      inQuote = false;
    }
  };
  const flushTable = () => {
    if (tableRows.length > 0) {
      const [head, ...body] = tableRows;
      output.push("<table><thead><tr>");
      head.forEach((cell) => output.push(`<th>${inline(cell)}</th>`));
      output.push("</tr></thead><tbody>");
      body.forEach((row) => {
        output.push("<tr>");
        row.forEach((cell) => output.push(`<td>${inline(cell)}</td>`));
        output.push("</tr>");
      });
      output.push("</tbody></table>");
      tableRows = [];
    }
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    if (line.startsWith("|") && line.endsWith("|")) {
      const cells = line.slice(1, -1).split("|").map((cell) => cell.trim());
      if (cells.every((cell) => /^[-: ]+$/.test(cell) && cell.length > 0)) continue;
      closeList();
      closeQuote();
      tableRows.push(cells);
      continue;
    }
    flushTable();

    if (line.startsWith("### ")) {
      closeList(); closeQuote();
      output.push(`<h3>${inline(line.slice(4))}</h3>`);
    } else if (line.startsWith("## ")) {
      closeList(); closeQuote();
      output.push(`<h2>${inline(line.slice(3))}</h2>`);
    } else if (line.startsWith("# ")) {
      closeList(); closeQuote();
      output.push(`<h1>${inline(line.slice(2))}</h1>`);
    } else if (line.startsWith("- ") || line.startsWith("* ")) {
      closeQuote();
      if (!inList) {
        output.push("<ul>");
        inList = true;
      }
      output.push(`<li>${inline(line.slice(2))}</li>`);
    } else if (line.startsWith("> ")) {
      closeList();
      if (!inQuote) {
        output.push("<blockquote>");
        inQuote = true;
      }
      output.push(`<p>${inline(line.slice(2))}</p>`);
    } else if (line === "---" || line === "***") {
      closeList(); closeQuote();
      output.push("<hr />");
    } else if (line.trim() === "") {
      closeList();
      closeQuote();
    } else {
      closeList(); closeQuote();
      output.push(`<p>${inline(line)}</p>`);
    }
  }
  closeList();
  closeQuote();
  flushTable();
  return output.join("\n");
}
