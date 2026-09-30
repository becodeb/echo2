import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Audience, FamilyOut, MeetingOut } from "../api/types";
import { AUDIENCES } from "./ClassificationPanel";
import { FamilySelect } from "./FamilySelect";
import { MeetingAiPlan } from "./MeetingAiPlan";
import { RecordToggle } from "./RecordToggle";
import { Select } from "./Select";
import { SegmentedToggle, Switch } from "./Toggles";
import { Button, Input, Modal, Spinner } from "./ui";
import { LEVEL_LABEL, useMyAccess, type Level } from "../state/access";
import { useAuth } from "../state/auth";
import { useInternalGroups } from "../state/internalGroups";

type Kind = "familia" | "equipo";

interface ProjectOption {
  id: string;
  name: string;
}

/**
 * Nueva reunión. Un solo formulario para los dos tipos:
 * - Familia: se elige la familia y con quién es.
 * - Equipo (reunión interna de un grupo): se elige el grupo, si se quiere acta
 *   y el proyecto. Proyecto solo existe acá: con las familias no tiene sentido.
 * Equipo aparece solo si la persona es de algún grupo.
 */
export function NewMeetingModal({
  open,
  onClose,
  initialKind = "familia",
  initialGroup = "",
}: {
  open: boolean;
  onClose: () => void;
  initialKind?: Kind;
  initialGroup?: string;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { activeOrg } = useAuth();
  const { data: myAccess } = useMyAccess();
  const { data: groupsData } = useInternalGroups();
  const myGroups = (groupsData?.groups ?? []).filter((group) => group.is_member);
  const canTeam = myGroups.length > 0;

  const [kindChoice, setKindChoice] = useState<Kind | null>(null);
  const kind: Kind = canTeam ? (kindChoice ?? initialKind) : "familia";

  const [title, setTitle] = useState("");
  const [language, setLanguage] = useState(() => localStorage.getItem("echo_pref_lang") ?? "es");
  const [participants, setParticipants] = useState("");
  const [recordAudio, setRecordAudio] = useState(false);
  // Quién habló (gasta un crédito en el plan Gratis) y si hablan menores.
  const [people, setPeople] = useState(false);
  const [minors, setMinors] = useState(false);
  // Familia
  const [familyId, setFamilyId] = useState("");
  const [audience, setAudience] = useState<Audience | "">("");
  const [visibility, setVisibility] = useState<"org" | "private">("org");
  const creatable = myAccess?.creatable_levels ?? [];
  const [levelChoice, setLevelChoice] = useState<Level | "">("");
  // Por defecto primaria si puede crear ahí (es donde está casi todo), si no el primero.
  const level = levelChoice || (creatable.includes("primaria") ? "primaria" : creatable[0] ?? "");
  // Equipo
  const [groupChoice, setGroupChoice] = useState("");
  const [wantsMinutes, setWantsMinutes] = useState(false);
  const [projectId, setProjectId] = useState("");
  const groupId = groupChoice || initialGroup || myGroups[0]?.id || "";
  const group = myGroups.find((item) => item.id === groupId);

  const { data: projects } = useQuery({
    queryKey: ["projects-options", activeOrg?.id],
    queryFn: () => api<ProjectOption[]>("/api/projects"),
    enabled: open && kind === "equipo" && !!activeOrg,
  });
  const { data: families } = useQuery({
    queryKey: ["families"],
    queryFn: () => api<FamilyOut[]>("/api/families"),
    enabled: open && kind === "familia",
  });
  const family = families?.find((item) => item.id === familyId);
  const today = new Date().toLocaleDateString("es");
  const defaultTitle =
    kind === "equipo"
      ? `${group?.name ?? "Reunión"} · ${today}`
      : family
        ? `${family.name} · ${today}`
        : `Reunión ${today}`;

  const participantList = participants
    .split(",")
    .map((name) => name.trim())
    .filter(Boolean)
    .map((name) => ({ name }));

  const create = useMutation({
    mutationFn: async () => {
      const common = {
        title: title.trim() || defaultTitle,
        language,
        record_audio: recordAudio,
        participants: participantList,
        people: people && !minors,
        minors,
      };
      const meeting = await api<MeetingOut>("/api/meetings", {
        method: "POST",
        body: JSON.stringify(
          kind === "equipo"
            ? { ...common, kind: "interna", group_id: groupId, minutes: wantsMinutes, project_id: projectId || null }
            : { ...common, visibility, level: level || null },
        ),
      });
      // La familia se guarda antes de grabar: así la seudonimización ya
      // prioriza sus nombres desde el primer minuto. Si esto falla no se
      // frena la reunión; se puede clasificar después desde el detalle.
      if (kind === "familia" && (familyId || audience)) {
        await api(`/api/meetings/${meeting.id}/classification`, {
          method: "PUT",
          body: JSON.stringify({ family_id: familyId || null, audience: audience || null }),
        }).catch(() => undefined);
      }
      return meeting;
    },
    onSuccess: (meeting) => {
      localStorage.setItem("echo_pref_lang", language);
      queryClient.invalidateQueries({ queryKey: ["billing"] });
      queryClient.invalidateQueries({ queryKey: ["meetings"] });
      queryClient.invalidateQueries({ queryKey: ["families"] });
      // El modal no se desmonta: que la próxima reunión arranque en blanco.
      setTitle("");
      setParticipants("");
      setFamilyId("");
      setAudience("");
      setRecordAudio(false);
      setPeople(false);
      setMinors(false);
      setWantsMinutes(false);
      setProjectId("");
      onClose();
      navigate(`/meetings/${meeting.id}/live`);
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (kind === "equipo" && !groupId) return;
    create.mutate();
  };

  return (
    <Modal open={open} onClose={onClose} title="Nueva reunión">
      <form onSubmit={submit} className="space-y-4">
        {canTeam && (
          <SegmentedToggle
            ariaLabel="Tipo de reunión"
            value={kind}
            onChange={setKindChoice}
            options={[
              { value: "equipo", label: "Equipo" },
              { value: "familia", label: "Familia" },
            ]}
          />
        )}

        {kind === "familia" ? (
          <div className="grid gap-4 rounded-xl bg-ink-50 p-4 sm:grid-cols-2">
            <FamilySelect value={familyId} onChange={setFamilyId} enabled={open} />
            <Select
              label="¿Con quién es?"
              value={audience}
              onChange={(next) => setAudience(next as Audience | "")}
              options={[{ value: "", label: "Sin definir" }, ...AUDIENCES]}
            />
          </div>
        ) : (
          <div className="space-y-3 rounded-xl bg-ink-50 p-4">
            <Select
              label="Grupo"
              value={groupId}
              onChange={setGroupChoice}
              options={myGroups.map((item) => ({ value: item.id, label: item.name, hint: `${item.members.length}` }))}
            />
            <p className="-mt-1 text-xs text-ink-400">
              La van a ver {group ? group.members.map((member) => member.name).join(", ") : "los integrantes del grupo"}.
            </p>
            <Switch
              checked={wantsMinutes}
              onChange={setWantsMinutes}
              label="Armar acta"
              hint={wantsMinutes ? "Además del resumen, Echo redacta el acta." : "Solo resumen y preguntas: sin acta."}
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
        )}

        <Input
          label={kind === "equipo" ? "Tema" : "Nombre"}
          placeholder={defaultTitle}
          value={title}
          onChange={(event) => setTitle(event.target.value)}
        />
        <div className="grid gap-4 sm:grid-cols-2">
          {kind === "familia" && creatable.length > 1 && (
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
        </div>
        <Input
          label="Participantes (separados por coma)"
          placeholder="Ana, Marcos, Juan"
          value={participants}
          onChange={(event) => setParticipants(event.target.value)}
        />
        {kind === "familia" && (
          <label className="flex items-center gap-2 text-sm text-ink-600">
            <input
              type="checkbox"
              checked={visibility === "private"}
              onChange={(event) => setVisibility(event.target.checked ? "private" : "org")}
              className="rounded border-ink-300"
            />
            Reunión privada (solo vos y con quien la compartas)
          </label>
        )}
        <RecordToggle checked={recordAudio} onChange={setRecordAudio} />
        <MeetingAiPlan
          people={people}
          onPeople={setPeople}
          minors={minors}
          onMinors={setMinors}
          minutes={kind === "familia" || wantsMinutes}
          enabled={open}
        />
        {create.isError && (
          <p className="text-sm text-red-600">
            {create.error instanceof Error ? create.error.message : "Error al crear"}
          </p>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button type="submit" disabled={create.isPending || (kind === "equipo" && !groupId)}>
            {create.isPending ? <Spinner /> : "Comenzar reunión"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
