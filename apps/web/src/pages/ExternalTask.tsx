import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { EchoFace } from "../components/EchoFace";
import { MarkdownView } from "../components/MarkdownView";
import { Button, Card, Spinner, formatDuration, formatMs } from "../components/ui";

type TaskStatus = "pending" | "in_progress" | "done" | "cancelled";

interface ExternalData {
  scope: "task" | "acta" | "meeting";
  scope_label: string;
  organization: string | null;
  assigned_by: string | null;
  assignee: string;
  task: { text: string; status: TaskStatus; due_date: string | null; due_text: string | null };
  meeting: { title: string; started_at: string; duration_seconds: number } | null;
  minutes_markdown: string | null;
  executive_summary: { points?: string[] } | null;
  transcript: { start_ms: number; speaker: string | null; text: string }[] | null;
}

/**
 * Lo que ve alguien de afuera de Echo al abrir el link del mail: la tarea que
 * le asignaron y, si quien se la asignó lo eligió, el acta o la reunión entera.
 * Sin cuenta: el link es la llave (routers/external.py).
 */
export default function ExternalTask() {
  const { token } = useParams<{ token: string }>();
  const [data, setData] = useState<ExternalData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"minutes" | "summary" | "transcript">("minutes");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetch(`/api/external/${token}`)
      .then(async (response) => {
        const body = await response.json().catch(() => null);
        if (!response.ok) throw new Error(body?.detail ?? "Este link no es válido o venció");
        setData(body);
      })
      .catch((err) => setError(err.message));
  }, [token]);

  const setStatus = async (status: TaskStatus) => {
    if (!data) return;
    setSaving(true);
    try {
      const response = await fetch(`/api/external/${token}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      if (response.ok) setData({ ...data, task: { ...data.task, status } });
    } finally {
      setSaving(false);
    }
  };

  if (error) {
    return (
      <div className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-[#fafbfc] px-6 text-center text-ink-500">
        <EchoFace mood="error" size={56} />
        <p>{error}</p>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-[#fafbfc] text-ink-300">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }

  const done = data.task.status === "done";
  const due = data.task.due_date
    ? new Date(data.task.due_date + "T00:00:00").toLocaleDateString("es", { weekday: "long", day: "numeric", month: "long" })
    : data.task.due_text;
  const tabs = (
    [
      ["minutes", "Acta", data.scope !== "task"],
      ["summary", "Resumen", data.scope === "meeting"],
      ["transcript", "Transcripción", data.scope === "meeting"],
    ] as const
  ).filter(([, , shown]) => shown);

  return (
    <div className="min-h-dvh bg-[#fafbfc]">
      <header className="border-b border-ink-100 bg-white px-4 py-4 sm:px-6">
        <div className="mx-auto flex max-w-3xl items-center gap-3">
          <span className="text-ink-900">
            <EchoFace mood="idle" size={28} />
          </span>
          <p className="min-w-0 text-sm text-ink-500">
            {data.assigned_by ?? "Alguien"}
            {data.organization && ` (${data.organization})`} te asignó una tarea
          </p>
        </div>
      </header>

      <main className="mx-auto max-w-3xl space-y-6 px-4 py-8 sm:px-6">
        <Card className="space-y-4">
          <p className={`text-lg leading-relaxed ${done ? "text-ink-400 line-through" : "text-ink-900"}`}>{data.task.text}</p>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-ink-500">
            {due && <span>Para {due}</span>}
            {data.meeting && (
              <span>
                De la reunión «{data.meeting.title}» del {new Date(data.meeting.started_at).toLocaleDateString("es")}
              </span>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {done ? (
              <>
                <span className="text-sm font-medium text-emerald-700">Hecha. Ya le avisamos a {data.assigned_by ?? "quien te la asignó"}.</span>
                <Button variant="ghost" onClick={() => setStatus("pending")} disabled={saving}>
                  Desmarcar
                </Button>
              </>
            ) : (
              <>
                <Button onClick={() => setStatus("done")} disabled={saving}>
                  {saving ? <Spinner /> : "Marcar como hecha"}
                </Button>
                {data.task.status !== "in_progress" && (
                  <Button variant="soft" onClick={() => setStatus("in_progress")} disabled={saving}>
                    La estoy haciendo
                  </Button>
                )}
              </>
            )}
          </div>
        </Card>

        {data.meeting && tabs.length > 0 && (
          <section>
            <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="font-semibold text-ink-900">{data.meeting.title}</h2>
              <p className="text-xs text-ink-400">
                {formatDuration(data.meeting.duration_seconds)} · Podés ver {data.scope_label}
              </p>
            </div>
            {tabs.length > 1 && (
              <nav className="mb-4 flex gap-1 overflow-x-auto border-b border-ink-100">
                {tabs.map(([value, label]) => (
                  <button
                    key={value}
                    onClick={() => setTab(value)}
                    className={`shrink-0 border-b-2 px-4 py-2.5 text-sm font-medium ${
                      tab === value ? "border-ink-900 text-ink-900" : "border-transparent text-ink-400"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </nav>
            )}
            {tab === "minutes" && (
              <Card>
                {data.minutes_markdown ? (
                  <MarkdownView markdown={data.minutes_markdown} />
                ) : (
                  <p className="text-sm text-ink-400">Esta reunión todavía no tiene acta.</p>
                )}
              </Card>
            )}
            {tab === "summary" && (
              <Card>
                {data.executive_summary?.points?.length ? (
                  <ul className="space-y-2">
                    {data.executive_summary.points.map((point, index) => (
                      <li key={index} className="flex gap-2.5 text-[15px] text-ink-800">
                        <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-accent-500" />
                        {point}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-ink-400">Esta reunión no tiene resumen.</p>
                )}
              </Card>
            )}
            {tab === "transcript" && (
              <div className="space-y-4">
                {data.transcript?.length ? (
                  data.transcript.map((segment, index) => (
                    <div key={index}>
                      <div className="mb-0.5 flex gap-2 text-xs text-ink-400">
                        <span className="font-mono tabular-nums">{formatMs(segment.start_ms)}</span>
                        {segment.speaker && <span className="font-medium">{segment.speaker}</span>}
                      </div>
                      <p className="text-[15px] leading-relaxed text-ink-900">{segment.text}</p>
                    </div>
                  ))
                ) : (
                  <p className="text-sm text-ink-400">Esta reunión no tiene transcripción.</p>
                )}
              </div>
            )}
          </section>
        )}

        <p className="text-center text-xs text-ink-400">El link es personal: no lo reenvíes.</p>
      </main>
    </div>
  );
}
