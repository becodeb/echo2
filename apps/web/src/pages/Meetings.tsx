import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Audience, FamilyOut, MeetingListItem, MeetingOut } from "../api/types";
import { AUDIENCES } from "../components/ClassificationPanel";
import { FamilySelect } from "../components/FamilySelect";
import { Select } from "../components/Select";
import { Badge, Button, Card, EmptyState, Input, Modal, Spinner, formatDate, formatDuration } from "../components/ui";
import { LEVEL_LABEL, useMyAccess, type Level } from "../state/access";
import { useAuth } from "../state/auth";

const STATUS: Record<string, { label: string; tone: "gray" | "red" | "amber" | "green" | "sky" }> = {
  draft: { label: "Borrador", tone: "gray" },
  live: { label: "En vivo", tone: "red" },
  paused: { label: "Pausada", tone: "amber" },
  processing: { label: "Procesando", tone: "sky" },
  completed: { label: "Completada", tone: "green" },
  failed: { label: "Falló", tone: "red" },
};

interface ProjectOption {
  id: string;
  name: string;
}

export default function Meetings() {
  const { activeOrg } = useAuth();
  const [params, setParams] = useSearchParams();
  const [showNew, setShowNew] = useState(params.get("new") === "1");

  useEffect(() => {
    if (params.get("new") === "1") setShowNew(true);
  }, [params]);

  const { data: meetings, isLoading } = useQuery({
    queryKey: ["meetings", activeOrg?.id],
    queryFn: () => api<MeetingListItem[]>("/api/meetings"),
    enabled: !!activeOrg,
  });

  return (
    <div className="mx-auto max-w-4xl px-6 py-10">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight text-ink-900">Reuniones</h1>
        <Button onClick={() => setShowNew(true)}>+ Nueva reunión</Button>
      </div>

      {isLoading && (
        <div className="flex justify-center py-16 text-ink-400">
          <Spinner className="h-6 w-6" />
        </div>
      )}

      {meetings && meetings.length === 0 && (
        <Card>
          <EmptyState title="Todavía no hay reuniones" mood="idle">
            Tocá «Nueva reunión», elegí tu micrófono y Echo escucha, transcribe y arma el acta por vos.
          </EmptyState>
        </Card>
      )}

      {meetings && meetings.length > 0 && (
        <Card className="divide-y divide-ink-100 p-0">
          {meetings.map((meeting) => {
            const status = STATUS[meeting.status] ?? STATUS.draft;
            const target =
              meeting.status === "completed" || meeting.status === "processing" || meeting.status === "failed"
                ? `/meetings/${meeting.id}`
                : `/meetings/${meeting.id}/live`;
            return (
              <Link key={meeting.id} to={target} className="flex items-center justify-between gap-4 px-5 py-4 transition-colors hover:bg-ink-50">
                <div className="min-w-0">
                  <p className="truncate font-medium text-ink-900">{meeting.title}</p>
                  <p className="mt-0.5 text-xs text-ink-400">
                    {formatDate(meeting.started_at ?? meeting.created_at)}
                    {meeting.duration_seconds > 0 && ` · ${formatDuration(meeting.duration_seconds)}`}
                    {meeting.participant_count > 0 && ` · ${meeting.participant_count} participantes`}
                    {meeting.project_name && ` · ${meeting.project_name}`}
                    {meeting.level && ` · ${LEVEL_LABEL[meeting.level] ?? meeting.level}`}
                  </p>
                </div>
                <Badge tone={status.tone}>
                  {meeting.status === "live" && <span className="recording-dot h-1.5 w-1.5 rounded-full bg-red-500" />}
                  {status.label}
                </Badge>
              </Link>
            );
          })}
        </Card>
      )}

      <NewMeetingModal
        open={showNew}
        onClose={() => {
          setShowNew(false);
          params.delete("new");
          setParams(params, { replace: true });
        }}
      />
    </div>
  );
}

function NewMeetingModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { activeOrg } = useAuth();
  const [title, setTitle] = useState("");
  const [language, setLanguage] = useState(() => localStorage.getItem("echo_pref_lang") ?? "es");
  const [projectId, setProjectId] = useState("");
  const [participants, setParticipants] = useState("");
  const [visibility, setVisibility] = useState<"org" | "private">("org");
  const [familyId, setFamilyId] = useState("");
  const [audience, setAudience] = useState<Audience | "">("");
  const { data: myAccess } = useMyAccess();
  const creatable = myAccess?.creatable_levels ?? [];
  const [levelChoice, setLevelChoice] = useState<Level | "">("");
  // Por defecto primaria si puede crear ahí (es donde está casi todo), si no el primero.
  const level = levelChoice || (creatable.includes("primaria") ? "primaria" : creatable[0] ?? "");

  const { data: projects } = useQuery({
    queryKey: ["projects-options", activeOrg?.id],
    queryFn: () => api<ProjectOption[]>("/api/projects"),
    enabled: open && !!activeOrg,
  });
  const { data: families } = useQuery({
    queryKey: ["families"],
    queryFn: () => api<FamilyOut[]>("/api/families"),
    enabled: open,
  });
  const family = families?.find((item) => item.id === familyId);
  const today = new Date().toLocaleDateString("es");
  const defaultTitle = family ? `${family.name} · ${today}` : `Reunión ${today}`;

  const create = useMutation({
    mutationFn: async () => {
      const meeting = await api<MeetingOut>("/api/meetings", {
        method: "POST",
        body: JSON.stringify({
          title: title.trim() || defaultTitle,
          language,
          project_id: projectId || null,
          visibility,
          level: level || null,
          participants: participants
            .split(",")
            .map((name) => name.trim())
            .filter(Boolean)
            .map((name) => ({ name })),
        }),
      });
      // La familia se guarda antes de grabar: así la seudonimización ya
      // prioriza sus nombres desde el primer minuto. Si esto falla no se
      // frena la reunión; se puede clasificar después desde el detalle.
      if (familyId || audience) {
        await api(`/api/meetings/${meeting.id}/classification`, {
          method: "PUT",
          body: JSON.stringify({ family_id: familyId || null, audience: audience || null }),
        }).catch(() => undefined);
      }
      return meeting;
    },
    onSuccess: (meeting) => {
      localStorage.setItem("echo_pref_lang", language);
      queryClient.invalidateQueries({ queryKey: ["meetings"] });
      queryClient.invalidateQueries({ queryKey: ["families"] });
      // El modal no se desmonta: que la próxima reunión arranque en blanco.
      setTitle("");
      setFamilyId("");
      setAudience("");
      onClose();
      navigate(`/meetings/${meeting.id}/live`);
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate();
  };

  return (
    <Modal open={open} onClose={onClose} title="Nueva reunión">
      <form onSubmit={submit} className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <FamilySelect value={familyId} onChange={setFamilyId} enabled={open} />
          <Select
            label="¿Con quién es?"
            value={audience}
            onChange={(next) => setAudience(next as Audience | "")}
            options={[{ value: "", label: "Sin definir" }, ...AUDIENCES]}
          />
        </div>
        <Input
          label="Nombre"
          placeholder={defaultTitle}
          value={title}
          onChange={(event) => setTitle(event.target.value)}
        />
        <div className="grid gap-4 sm:grid-cols-2">
          {creatable.length > 1 && (
            <Select
              label="Nivel"
              value={level}
              onChange={(next) => setLevelChoice(next as Level)}
              options={creatable.map((value) => ({ value, label: LEVEL_LABEL[value] }))}
            />
          )}
          <Select
            label="Idioma"
            value={language}
            onChange={setLanguage}
            options={[
              { value: "es", label: "Español" },
              { value: "en", label: "English" },
              { value: "pt", label: "Português" },
              { value: "auto", label: "Detectar automáticamente" },
            ]}
          />
          <Select
            label="Proyecto"
            value={projectId}
            onChange={setProjectId}
            options={[
              { value: "", label: "Sin proyecto" },
              ...(projects ?? []).map((project) => ({ value: project.id, label: project.name })),
            ]}
            searchPlaceholder="Buscar proyecto…"
          />
        </div>
        <Input
          label="Participantes (separados por coma)"
          placeholder="Ana, Marcos, Juan"
          value={participants}
          onChange={(event) => setParticipants(event.target.value)}
        />
        <label className="flex items-center gap-2 text-sm text-ink-600">
          <input
            type="checkbox"
            checked={visibility === "private"}
            onChange={(event) => setVisibility(event.target.checked ? "private" : "org")}
            className="rounded border-ink-300"
          />
          Reunión privada (solo vos y con quien la compartas)
        </label>
        {create.isError && (
          <p className="text-sm text-red-600">
            {create.error instanceof Error ? create.error.message : "Error al crear"}
          </p>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button type="submit" disabled={create.isPending}>
            {create.isPending ? <Spinner /> : "Comenzar reunión"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
