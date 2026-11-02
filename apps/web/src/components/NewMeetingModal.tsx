import { useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Audience, FamilyOut, MeetingOut, ScheduledMeetingOut } from "../api/types";
import { dayLabel, isoDay } from "../lib/agenda";
import { AUDIENCES } from "./ClassificationPanel";
import { FamilySelect } from "./FamilySelect";
import { usePaid } from "./billing";
import { MeetingAiPlan } from "./MeetingAiPlan";
import { PeoplePicker } from "./PeoplePicker";
import { SedePicker } from "./SedePicker";
import { StudentPicker, onlyStudent } from "./StudentPicker";
import { RecordToggle } from "./RecordToggle";
import { SettingsGroup } from "./SettingRows";
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
  initialFamily = "",
  scheduled,
}: {
  open: boolean;
  onClose: () => void;
  initialKind?: Kind;
  initialGroup?: string;
  /** Desde la página de una familia: la reunión ya viene con ella. */
  initialFamily?: string;
  /** Desde la Agenda: la reunión arranca con todo lo que se cargó al agendarla. */
  scheduled?: ScheduledMeetingOut;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { activeOrg, user } = useAuth();
  const { data: myAccess } = useMyAccess();
  const { data: groupsData } = useInternalGroups();
  const myGroups = (groupsData?.groups ?? []).filter((group) => group.is_member);
  const canTeam = myGroups.length > 0;

  const [kindChoice, setKindChoice] = useState<Kind | null>(
    scheduled ? (scheduled.kind === "interna" ? "equipo" : "familia") : null,
  );
  // Agendada: primero el resumen de lo cargado; "Cambiar" abre el formulario.
  const [summary, setSummary] = useState(!!scheduled);
  const kind: Kind = canTeam ? (kindChoice ?? initialKind) : "familia";

  const [title, setTitle] = useState("");
  const [language, setLanguage] = useState(() => localStorage.getItem("echo_pref_lang") ?? "es");
  const [participants, setParticipants] = useState("");
  // Quiénes del colegio están: con eso la ven (además de quien la crea).
  const [staff, setStaff] = useState<string[]>(
    (scheduled?.staff ?? []).map((person) => person.id).filter((id) => id !== user?.id),
  );
  const [recordAudio, setRecordAudio] = useState(false);
  // Quién habló (gasta un crédito en el plan Gratis) y si hablan menores.
  const [people, setPeople] = useState(false);
  const [minors, setMinors] = useState(false);
  // Familia
  const [familyId, setFamilyId] = useState(scheduled?.family_id ?? initialFamily);
  const [students, setStudents] = useState<string[]>((scheduled?.students ?? []).map((student) => student.id));
  const [intersede, setIntersede] = useState(false);
  const [audience, setAudience] = useState<Audience | "">("");
  const [visibility, setVisibility] = useState<"org" | "private">("org");
  const creatable = myAccess?.creatable_levels ?? [];
  const [levelChoice, setLevelChoice] = useState<Level | "">((scheduled?.level as Level | null) ?? "");
  // Equipo
  const [groupChoice, setGroupChoice] = useState(scheduled?.group_id ?? "");
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
  // Por defecto el nivel del hijo de la reunión, si puede crear ahí; si no,
  // primaria (es donde está casi todo) o el primero.
  const kids = students.length ? students : onlyStudent(family);
  const childLevel = family?.members.find((member) => kids.includes(member.id) && member.level)?.level;
  const level =
    levelChoice ||
    (childLevel && creatable.includes(childLevel)
      ? childLevel
      : creatable.includes("primaria")
        ? "primaria"
        : (creatable[0] ?? ""));
  const today = new Date().toLocaleDateString("es");
  const defaultTitle =
    kind === "equipo"
      ? `${group?.name ?? "Reunión"} · ${today}`
      : family
        ? `${family.name} · ${today}`
        : `Reunión ${today}`;

  // "Laura Gómez - psicopedagoga" o "Ana (maestra integradora)": con el rol,
  // Echo reconoce quién es cada voz y arma "Qué dijo cada uno".
  const participantList = participants
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean)
    .map((entry) => {
      // El guion necesita espacio antes: "Ana-Laura" es un nombre, no "Ana" con rol "Laura".
      const match = entry.match(/^(.+?)\s*\((.+)\)$/) ?? entry.match(/^(.+?)\s+[-–—:]\s*(.+)$/);
      const name = (match ? match[1] : entry).trim();
      const role = match ? match[2].trim() : "";
      return role ? { name, role_label: role } : { name };
    });

  // Importar la grabación de una reunión que ya pasó (Zoom, Meet, el celular):
  // es de los planes pagos.
  const paid = usePaid();
  const fileInput = useRef<HTMLInputElement>(null);
  const [upload, setUpload] = useState<File | null>(null);

  const create = useMutation({
    mutationFn: async (file?: File) => {
      const common = {
        title: title.trim() || defaultTitle,
        language,
        record_audio: recordAudio,
        participants: participantList,
        staff_ids: staff,
        people: people && !minors,
        minors,
        scheduled_id: scheduled?.id ?? null,
      };
      const meeting = await api<MeetingOut>("/api/meetings", {
        method: "POST",
        body: JSON.stringify(
          kind === "equipo"
            ? { ...common, kind: "interna", group_id: groupId, minutes: wantsMinutes, project_id: projectId || null }
            : { ...common, visibility, level: level || null, intersede },
        ),
      });
      // La familia se guarda antes de grabar: así la seudonimización ya
      // prioriza sus nombres desde el primer minuto. Si esto falla no se
      // frena la reunión; se puede clasificar después desde el detalle.
      const reasonId = scheduled?.reason_id ?? null;
      if (kind === "familia" && (familyId || audience || reasonId)) {
        await api(`/api/meetings/${meeting.id}/classification`, {
          method: "PUT",
          body: JSON.stringify({
            family_id: familyId || null,
            audience: audience || null,
            ...(reasonId ? { reason_id: reasonId } : {}),
            student_ids: familyId ? (students.length ? students : onlyStudent(family)) : [],
          }),
        }).catch(() => undefined);
      }
      if (file) {
        const form = new FormData();
        form.append("file", file, file.name);
        await api(`/api/meetings/${meeting.id}/import`, { method: "POST", body: form });
      }
      return { meeting, imported: !!file };
    },
    onSuccess: ({ meeting, imported }) => {
      localStorage.setItem("echo_pref_lang", language);
      queryClient.invalidateQueries({ queryKey: ["billing"] });
      queryClient.invalidateQueries({ queryKey: ["meetings"] });
      queryClient.invalidateQueries({ queryKey: ["families"] });
      queryClient.invalidateQueries({ queryKey: ["agenda"] });
      // El modal no se desmonta: que la próxima reunión arranque en blanco.
      setTitle("");
      setParticipants("");
      setStaff([]);
      setFamilyId(initialFamily);
      setStudents([]);
      setIntersede(false);
      setAudience("");
      setRecordAudio(false);
      setPeople(false);
      setMinors(false);
      setWantsMinutes(false);
      setProjectId("");
      setUpload(null);
      onClose();
      navigate(imported ? `/meetings/${meeting.id}` : `/meetings/${meeting.id}/live`);
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (kind === "equipo" && !groupId) return;
    create.mutate(upload ?? undefined);
  };

  if (scheduled && summary) {
    const today = isoDay(new Date());
    const rows: [string, string][] = [
      ...(scheduled.students.length
        ? [["Alumno/a", scheduled.students.map((s) => (s.curso ? `${s.name} · ${s.curso}` : s.name)).join(", ")] as [string, string]]
        : []),
      ...(scheduled.reason_name ? [["Motivo", scheduled.reason_name] as [string, string]] : []),
      ...(scheduled.level ? [["Nivel", LEVEL_LABEL[scheduled.level]] as [string, string]] : []),
      ["Por el colegio", ["Vos", ...scheduled.staff.filter((p) => p.id !== user?.id).map((p) => p.name)].join(", ")],
      ...(scheduled.note ? [["Nota", scheduled.note] as [string, string]] : []),
    ];
    return (
      <Modal open={open} onClose={onClose} title="Empezar la reunión agendada">
        <div className="space-y-4">
          <div>
            <p className="text-sm font-medium text-accent-600">
              {scheduled.date === today ? "Agendada para hoy" : `Agendada para el ${dayLabel(scheduled.date).toLowerCase()}`}
              {scheduled.time ? `, ${scheduled.time}` : ""}
            </p>
            <h3 className="mt-0.5 text-xl font-semibold text-ink-900">
              {scheduled.kind === "interna" ? `Reunión interna · ${scheduled.group_name ?? ""}` : (scheduled.family_name ?? "Reunión")}
            </h3>
          </div>
          <dl className="grid grid-cols-[7.5rem_minmax(0,1fr)] gap-x-3 gap-y-2.5 rounded-2xl border border-ink-100 p-4 text-sm">
            {rows.map(([label, value]) => (
              <div key={label} className="contents">
                <dt className="text-ink-500">{label}</dt>
                <dd className="font-medium text-ink-900">{value}</dd>
              </div>
            ))}
          </dl>
          <p className="text-sm text-ink-500">
            {scheduled.kind === "interna"
              ? "La reunión arranca en el grupo, con quienes sumaste."
              : "Todo esto ya va al acta: alumno, curso, motivo y quiénes estuvieron. Si algo cambió, tocá «Cambiar»."}
          </p>
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
          <div className="flex flex-wrap items-center justify-end gap-2 pt-1">
            <Button type="button" variant="ghost" onClick={() => setSummary(false)}>
              Cambiar
            </Button>
            <Button
              type="button"
              className="min-h-12 bg-red-600 px-6 text-base hover:bg-red-500"
              onClick={() => create.mutate(undefined)}
              disabled={create.isPending}
            >
              {create.isPending ? <Spinner /> : "Empezar a grabar"}
            </Button>
          </div>
        </div>
      </Modal>
    );
  }

  return (
    <Modal open={open} onClose={onClose} title={scheduled ? "Empezar la reunión agendada" : "Nueva reunión"}>
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

        {kind === "familia" && <SedePicker intersede={intersede} onIntersede={setIntersede} />}

        {kind === "familia" ? (
          <div className="grid gap-4 rounded-2xl bg-ink-50 p-4 sm:grid-cols-2">
            <FamilySelect
              value={familyId}
              onChange={(next) => {
                setFamilyId(next);
                setStudents([]);
              }}
              enabled={open}
            />
            <Select
              label="¿Con quién es?"
              value={audience}
              onChange={(next) => setAudience(next as Audience | "")}
              options={[{ value: "", label: "Sin definir" }, ...AUDIENCES]}
            />
            <StudentPicker family={family} value={students} onChange={setStudents} />
          </div>
        ) : (
          <div className="space-y-3 rounded-2xl bg-ink-50 p-4">
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
        </div>
        {kind === "familia" && (
          <PeoplePicker
            label="¿Quiénes del colegio están?"
            hint="La ven vos, quienes sumes acá, quienes tienen asignada la familia y los directivos."
            value={staff}
            onChange={setStaff}
            exclude={user ? [user.id] : []}
            enabled={open}
          />
        )}
        <Input
          label={kind === "familia" ? "Otros participantes, con su rol" : "Participantes, con su rol"}
          placeholder="Laura Gómez - psicopedagoga, Ana (maestra integradora)"
          value={participants}
          onChange={(event) => setParticipants(event.target.value)}
        />
        <details className="group rounded-2xl border border-ink-100 px-4 py-1">
          <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between text-sm font-medium text-ink-700">
            Opciones avanzadas
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" className="transition-transform group-open:rotate-180" aria-hidden>
              <path d="m6 9 6 6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </summary>
          <div className="space-y-4 pb-4 pt-2">
            <Select
              label="Idioma"
              value={language}
              onChange={setLanguage}
              options={[
                { value: "es", label: "Español" },
                { value: "en", label: "English" },
                { value: "pt", label: "Português" },
                { value: "multi", label: "Varios idiomas (español, inglés, otro)" },
              ]}
            />
            <p className="-mt-2 text-xs text-ink-400">
              Con varios idiomas (una familia que habla inglés, un traductor) Echo transcribe cada uno como se habló.
              El acta, el resumen y las tareas salen igual en castellano.
            </p>
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
            <SettingsGroup>
              <RecordToggle checked={recordAudio} onChange={setRecordAudio} internal={kind === "equipo"} />
            </SettingsGroup>
          </div>
        </details>
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
        <div className="rounded-2xl border border-dashed border-ink-200 px-4 py-3">
          {paid === false ? (
            <p className="text-sm text-ink-500">
              ¿Ya tenés la grabación (Zoom, Meet, el celular)? Subirla es parte de los planes pagos.{" "}
              <Link to="/plans" onClick={onClose} className="font-medium text-ink-800 underline-offset-2 hover:underline">
                Ver planes
              </Link>
            </p>
          ) : upload ? (
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="min-w-0 flex-1 truncate text-ink-700">
                Grabación: <strong className="font-medium text-ink-900">{upload.name}</strong>
              </span>
              <button type="button" onClick={() => setUpload(null)} className="min-h-9 px-2 text-ink-500 hover:text-ink-900">
                Quitar
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => fileInput.current?.click()}
              className="min-h-9 text-left text-sm text-ink-600 hover:text-ink-900"
            >
              ¿Ya tenés la grabación (Zoom, Meet, el celular)? <span className="font-medium text-ink-900 underline underline-offset-2">Subila</span>
            </button>
          )}
          <input
            ref={fileInput}
            type="file"
            accept=".mp3,.wav,.m4a,.webm,.mp4,.ogg,.flac,audio/*,video/mp4"
            className="hidden"
            onChange={(event) => setUpload(event.target.files?.[0] ?? null)}
          />
        </div>
        <p className="flex items-start gap-2 text-xs leading-relaxed text-ink-500">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" className="mt-0.5 shrink-0" aria-hidden>
            <rect x="5" y="11" width="14" height="10" rx="3" stroke="currentColor" strokeWidth="2" />
            <path d="M8 11V8a4 4 0 0 1 8 0v3" stroke="currentColor" strokeWidth="2" />
          </svg>
          Los nombres se reemplazan antes de que la IA lea la reunión, y el audio se borra al terminar.
        </p>
        {/* En el celular el botón queda fijo abajo: el formulario es largo. */}
        <div className="sticky bottom-0 -mx-5 flex justify-end gap-2 border-t border-ink-100 bg-white px-5 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3 sm:static sm:mx-0 sm:border-0 sm:p-0 sm:pt-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button
            type="button"
            onClick={() => create.mutate(upload ?? undefined)}
            disabled={create.isPending || (kind === "equipo" && !groupId)}
          >
            {create.isPending ? <Spinner /> : upload ? "Subir y procesar" : "Comenzar reunión"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
