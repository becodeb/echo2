import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { InternalGroupOut, MeetingListItem, MeetingOut } from "../api/types";
import { MeetingList } from "../components/MeetingList";
import { RecordToggle } from "../components/RecordToggle";
import { Select } from "../components/Select";
import { Badge, Button, Card, EmptyState, Input, Modal, Spinner } from "../components/ui";
import { useAuth } from "../state/auth";
import { useInternalGroups } from "../state/internalGroups";

/**
 * Reuniones entre directivos, coordinadores y otros equipos, sin alumno de por
 * medio. Cada una es de un grupo y la ve solo ese grupo (ni siquiera los
 * admins de la sede, salvo que se sumen). No tienen acta: lo que importa es
 * el resumen, poder preguntarle y, si se quiere, la grabación.
 */
export default function InternalMeetings() {
  const { activeOrg } = useAuth();
  const { data: groupsData, isLoading: loadingGroups } = useInternalGroups();
  const [groupFilter, setGroupFilter] = useState("");
  const [creating, setCreating] = useState(false);
  const [managing, setManaging] = useState(false);

  const myGroups = (groupsData?.groups ?? []).filter((group) => group.is_member);

  const { data: meetings, isLoading } = useQuery({
    queryKey: ["meetings", activeOrg?.id, "interna", groupFilter],
    queryFn: () =>
      api<MeetingListItem[]>(`/api/meetings?kind=interna${groupFilter ? `&group_id=${groupFilter}` : ""}`),
    enabled: !!activeOrg,
  });

  return (
    <div className="mx-auto max-w-4xl space-y-5 px-6 py-10">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink-900">Reuniones internas</h1>
          <p className="mt-1 text-sm text-ink-500">
            Entre directivos, coordinadores y equipos. Cada reunión la ve solo su grupo.
          </p>
        </div>
        <div className="flex gap-2">
          {groupsData?.can_manage && (
            <Button variant="soft" onClick={() => setManaging(true)}>
              Grupos
            </Button>
          )}
          {myGroups.length > 0 && <Button onClick={() => setCreating(true)}>+ Nueva reunión interna</Button>}
        </div>
      </div>

      {myGroups.length > 1 && (
        <div className="flex flex-wrap gap-1.5">
          {[{ id: "", name: "Todas" }, ...myGroups].map((group) => (
            <button
              key={group.id}
              onClick={() => setGroupFilter(group.id)}
              aria-pressed={groupFilter === group.id}
              className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                groupFilter === group.id
                  ? "border-ink-900 bg-ink-900 text-white"
                  : "border-ink-200 bg-white text-ink-600 hover:border-ink-300 hover:text-ink-900"
              }`}
            >
              {group.name}
            </button>
          ))}
        </div>
      )}

      {(isLoading || loadingGroups) && (
        <div className="flex justify-center py-16 text-ink-400">
          <Spinner className="h-6 w-6" />
        </div>
      )}

      {!loadingGroups && myGroups.length === 0 && (
        <Card>
          <EmptyState title="Todavía no sos parte de ningún grupo" mood="idle">
            {groupsData?.can_manage ? (
              <>
                <p className="mb-4">
                  Sumá a las personas a Directivos, Coordinadores o al grupo que armes. Si vos también
                  participás, sumate: las reuniones de un grupo solo las ven sus integrantes.
                </p>
                <Button onClick={() => setManaging(true)}>Administrar grupos</Button>
              </>
            ) : (
              <p>Pedile a dirección que te sume a un grupo.</p>
            )}
          </EmptyState>
        </Card>
      )}

      {myGroups.length > 0 && meetings && meetings.length === 0 && (
        <Card>
          <EmptyState title="Todavía no hay reuniones internas" mood="idle">
            Grabá la próxima reunión de equipo: Echo la transcribe, te arma el resumen y después le
            podés preguntar lo que se habló.
          </EmptyState>
        </Card>
      )}

      {meetings && meetings.length > 0 && <MeetingList meetings={meetings} />}

      <NewInternalMeetingModal
        open={creating}
        onClose={() => setCreating(false)}
        groups={myGroups}
        initialGroup={groupFilter}
      />
      {groupsData?.can_manage && (
        <ManageGroupsModal open={managing} onClose={() => setManaging(false)} groups={groupsData.groups} />
      )}
    </div>
  );
}

function NewInternalMeetingModal({
  open,
  onClose,
  groups,
  initialGroup,
}: {
  open: boolean;
  onClose: () => void;
  groups: InternalGroupOut[];
  initialGroup: string;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [groupChoice, setGroupChoice] = useState("");
  const [title, setTitle] = useState("");
  const [participants, setParticipants] = useState("");
  const [recordAudio, setRecordAudio] = useState(true);
  const groupId = groupChoice || initialGroup || groups[0]?.id || "";
  const group = groups.find((item) => item.id === groupId);
  const defaultTitle = `${group?.name ?? "Reunión"} · ${new Date().toLocaleDateString("es")}`;

  const create = useMutation({
    mutationFn: () =>
      api<MeetingOut>("/api/meetings", {
        method: "POST",
        body: JSON.stringify({
          title: title.trim() || defaultTitle,
          kind: "interna",
          group_id: groupId,
          record_audio: recordAudio,
          participants: participants
            .split(",")
            .map((name) => name.trim())
            .filter(Boolean)
            .map((name) => ({ name })),
        }),
      }),
    onSuccess: (meeting) => {
      queryClient.invalidateQueries({ queryKey: ["meetings"] });
      setTitle("");
      setParticipants("");
      onClose();
      navigate(`/meetings/${meeting.id}/live`);
    },
  });

  return (
    <Modal open={open} onClose={onClose} title="Nueva reunión interna">
      <form
        onSubmit={(event: FormEvent) => {
          event.preventDefault();
          if (groupId) create.mutate();
        }}
        className="space-y-4"
      >
        <Select
          label="Grupo"
          value={groupId}
          onChange={setGroupChoice}
          options={groups.map((item) => ({ value: item.id, label: item.name, hint: `${item.members.length}` }))}
        />
        <p className="-mt-2 text-xs text-ink-400">
          La van a ver {group ? group.members.map((member) => member.name).join(", ") : "los integrantes del grupo"}.
        </p>
        <Input
          label="Tema"
          placeholder={defaultTitle}
          value={title}
          onChange={(event) => setTitle(event.target.value)}
        />
        <Input
          label="Participantes (separados por coma)"
          placeholder="Ana, Marcos, Juan"
          value={participants}
          onChange={(event) => setParticipants(event.target.value)}
        />
        <RecordToggle checked={recordAudio} onChange={setRecordAudio} />
        {create.isError && (
          <p className="text-sm text-red-600">
            {create.error instanceof Error ? create.error.message : "No se pudo crear"}
          </p>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button type="submit" disabled={!groupId || create.isPending}>
            {create.isPending ? <Spinner /> : "Comenzar reunión"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

interface OrgMember {
  user_id: string;
  name: string;
  email: string;
}

function ManageGroupsModal({
  open,
  onClose,
  groups,
}: {
  open: boolean;
  onClose: () => void;
  groups: InternalGroupOut[];
}) {
  const queryClient = useQueryClient();
  const { activeOrg } = useAuth();
  const [newGroup, setNewGroup] = useState("");
  const [adding, setAdding] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  const { data: members } = useQuery({
    queryKey: ["org-members", activeOrg?.id],
    queryFn: () => api<OrgMember[]>("/api/org/members"),
    enabled: open,
  });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["internal-groups"] });
    queryClient.invalidateQueries({ queryKey: ["meetings"] });
  };
  const onError = (err: unknown) => setError(err instanceof Error ? err.message : "No se pudo guardar");

  const createGroup = useMutation({
    mutationFn: () => api("/api/internal-groups", { method: "POST", body: JSON.stringify({ name: newGroup }) }),
    onSuccess: () => {
      setNewGroup("");
      setError(null);
      refresh();
    },
    onError,
  });
  const deleteGroup = useMutation({
    mutationFn: (groupId: string) => api(`/api/internal-groups/${groupId}`, { method: "DELETE" }),
    onSuccess: refresh,
    onError,
  });
  const addMember = useMutation({
    mutationFn: ({ groupId, userId }: { groupId: string; userId: string }) =>
      api(`/api/internal-groups/${groupId}/members/${userId}`, { method: "PUT" }),
    onSuccess: (_, { groupId }) => {
      setAdding((current) => ({ ...current, [groupId]: "" }));
      setError(null);
      refresh();
    },
    onError,
  });
  const removeMember = useMutation({
    mutationFn: ({ groupId, userId }: { groupId: string; userId: string }) =>
      api(`/api/internal-groups/${groupId}/members/${userId}`, { method: "DELETE" }),
    onSuccess: refresh,
    onError,
  });

  return (
    <Modal open={open} onClose={onClose} title="Grupos internos" wide>
      <div className="space-y-5">
        <p className="text-sm text-ink-500">
          Las reuniones de un grupo las ven solo sus integrantes, incluso para los admins de la sede.
          Sumar o sacar a alguien queda registrado.
        </p>
        {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

        {groups.map((group) => {
          const inGroup = new Set(group.members.map((member) => member.user_id));
          const candidates = (members ?? []).filter((member) => !inGroup.has(member.user_id));
          return (
            <div key={group.id} className="space-y-2 rounded-xl border border-ink-100 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="font-semibold text-ink-900">
                  {group.name}{" "}
                  <span className="text-sm font-normal text-ink-400">
                    · {group.meetings} {group.meetings === 1 ? "reunión" : "reuniones"}
                  </span>
                </h3>
                {group.meetings === 0 && (
                  <button
                    onClick={() => deleteGroup.mutate(group.id)}
                    className="text-xs text-ink-400 hover:text-red-600"
                  >
                    Borrar grupo
                  </button>
                )}
              </div>
              {group.members.length === 0 ? (
                <p className="text-sm text-ink-500">Sin integrantes todavía.</p>
              ) : (
                <ul className="flex flex-wrap gap-1.5">
                  {group.members.map((member) => (
                    <li key={member.user_id}>
                      <Badge tone="indigo">
                        {member.name}
                        <button
                          onClick={() => removeMember.mutate({ groupId: group.id, userId: member.user_id })}
                          className="ml-1 text-indigo-400 hover:text-red-600"
                          aria-label={`Sacar a ${member.name}`}
                        >
                          ×
                        </button>
                      </Badge>
                    </li>
                  ))}
                </ul>
              )}
              {candidates.length > 0 && (
                <div className="flex flex-wrap items-center gap-2">
                  <Select
                    ariaLabel={`Sumar a ${group.name}`}
                    size="sm"
                    value={adding[group.id] ?? ""}
                    onChange={(userId) => setAdding((current) => ({ ...current, [group.id]: userId }))}
                    options={candidates.map((member) => ({
                      value: member.user_id,
                      label: member.name,
                      hint: member.email,
                    }))}
                    placeholder="Sumar a alguien…"
                    searchPlaceholder="Buscar persona…"
                    className="min-w-[200px] flex-1 sm:max-w-xs"
                  />
                  <Button
                    variant="soft"
                    disabled={!adding[group.id] || addMember.isPending}
                    onClick={() => addMember.mutate({ groupId: group.id, userId: adding[group.id] })}
                  >
                    Sumar
                  </Button>
                </div>
              )}
            </div>
          );
        })}

        <form
          onSubmit={(event: FormEvent) => {
            event.preventDefault();
            if (newGroup.trim()) createGroup.mutate();
          }}
          className="flex flex-wrap items-end gap-2 border-t border-ink-100 pt-4"
        >
          <div className="min-w-[200px] flex-1">
            <Input
              label="Nuevo grupo"
              placeholder="Equipo de orientación, Consejo académico…"
              value={newGroup}
              onChange={(event) => setNewGroup(event.target.value)}
            />
          </div>
          <Button type="submit" variant="soft" disabled={!newGroup.trim() || createGroup.isPending}>
            Crear grupo
          </Button>
        </form>
      </div>
    </Modal>
  );
}
