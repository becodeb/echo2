import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { EchoFace } from "../components/EchoFace";
import { Card, Spinner, formatDuration, formatMs } from "../components/ui";
import { MarkdownView } from "./MeetingDetail";

interface SharedData {
  meeting: { title: string; started_at: string | null; duration_seconds: number };
  role: string;
  allow_download: boolean;
  executive_summary: { points?: string[] } | null;
  minutes_markdown: string | null;
  transcript: { seq: number; start_ms: number; speaker: string | null; text: string }[];
}

export default function SharedView() {
  const { token } = useParams<{ token: string }>();
  const [data, setData] = useState<SharedData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"summary" | "minutes" | "transcript">("summary");

  useEffect(() => {
    fetch(`/api/shared/${token}`)
      .then(async (response) => {
        if (!response.ok) throw new Error("Este link no es válido o expiró");
        setData(await response.json());
      })
      .catch((err) => setError(err.message));
  }, [token]);

  if (error) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-[#fafbfc] text-ink-500">
        <EchoFace mood="error" size={56} />
        <p>{error}</p>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#fafbfc] text-ink-300">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#fafbfc]">
      <header className="border-b border-ink-100 bg-white px-6 py-4">
        <div className="mx-auto flex max-w-3xl items-center gap-3">
          <span className="text-ink-900"><EchoFace mood="idle" size={28} /></span>
          <div>
            <h1 className="font-semibold text-ink-900">{data.meeting.title}</h1>
            <p className="text-xs text-ink-400">
              {data.meeting.started_at && new Date(data.meeting.started_at).toLocaleDateString("es")}
              {" · "}
              {formatDuration(data.meeting.duration_seconds)} · compartida con Echo
            </p>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-6 py-8">
        <nav className="mb-6 flex gap-1 border-b border-ink-100">
          {(
            [
              ["summary", "Resumen"],
              ["minutes", "Acta"],
              ["transcript", "Transcript"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              onClick={() => setTab(value)}
              className={`border-b-2 px-4 py-2.5 text-sm font-medium ${
                tab === value ? "border-ink-900 text-ink-900" : "border-transparent text-ink-400"
              }`}
            >
              {label}
            </button>
          ))}
        </nav>

        {tab === "summary" && (
          <Card>
            {data.executive_summary?.points ? (
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

        {tab === "minutes" && (
          <Card>
            {data.minutes_markdown ? (
              <MarkdownView markdown={data.minutes_markdown} />
            ) : (
              <p className="text-sm text-ink-400">Esta reunión no tiene acta.</p>
            )}
          </Card>
        )}

        {tab === "transcript" && (
          <div className="space-y-4">
            {data.transcript.map((segment) => (
              <div key={segment.seq}>
                <div className="mb-0.5 flex gap-2 text-xs text-ink-400">
                  <span className="font-mono tabular-nums">{formatMs(segment.start_ms)}</span>
                  {segment.speaker && <span className="font-medium">{segment.speaker}</span>}
                </div>
                <p className="text-[15px] leading-relaxed text-ink-900">{segment.text}</p>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
