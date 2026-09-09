import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { FamilyMemberOut, FamilyOut } from "../api/types";
import { Badge, Button, Card, EmptyState, Input, Modal, Spinner } from "../components/ui";

const RELATIONSHIPS: FamilyMemberOut["relationship_type"][] = [
  "madre",
  "padre",
  "tutor",
  "estudiante",
  "otro",
];

function MemberList({ family }: { family: FamilyOut }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [relationship, setRelationship] =
    useState<FamilyMemberOut["relationship_type"]>("madre");

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["families"] });

  const add = useMutation({
    mutationFn: () =>
      api<FamilyMemberOut>(`/api/families/${family.id}/members`, {
        method: "POST",
        body: JSON.stringify({
          name,
          relationship_type: relationship,
          // El estudiante no es responsable: su ausencia no cuenta como
          // "faltó un tutor".
          is_guardian: relationship !== "estudiante",
        }),
      }),
    onSuccess: () => {
      setName("");
      setRelationship("madre");
      invalidate();
    },
  });

  const remove = useMutation({
    mutationFn: (memberId: string) =>
      api(`/api/families/members/${memberId}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (name.trim()) add.mutate();
  };

  return (
    <div className="space-y-3 border-t border-ink-100 pt-4">
      {family.members.length === 0 ? (
        <p className="text-sm text-ink-500">
          Todavía no hay integrantes. Cargá al menos a los responsables: son contra quienes se
          mide si vinieron todos.
        </p>
      ) : (
        <ul className="space-y-1.5">
          {family.members.map((member) => (
            <li key={member.id} className="flex items-center gap-2 text-sm">
              <span className="text-ink-800">{member.name}</span>
              <Badge tone={member.is_guardian ? "indigo" : "gray"}>
                {member.relationship_type}
              </Badge>
              <button
                onClick={() => remove.mutate(member.id)}
                className="ml-auto text-xs text-ink-400 hover:text-red-600"
              >
                Quitar
              </button>
            </li>
          ))}
        </ul>
      )}

      <form onSubmit={submit} className="flex flex-wrap items-end gap-2">
        <div className="min-w-[160px] flex-1">
          <Input
            label="Agregar integrante"
            placeholder="Nombre y apellido"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </div>
        <select
          value={relationship}
          onChange={(event) =>
            setRelationship(event.target.value as FamilyMemberOut["relationship_type"])
          }
          className="rounded-lg border border-ink-200 px-3 py-2 text-sm"
        >
          {RELATIONSHIPS.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
        <Button type="submit" variant="soft" disabled={add.isPending}>
          {add.isPending ? <Spinner /> : "Agregar"}
        </Button>
      </form>
    </div>
  );
}

export default function Families() {
  const queryClient = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", reference: "" });
  const [search, setSearch] = useState("");

  const { data: families, isLoading } = useQuery({
    queryKey: ["families"],
    queryFn: () => api<FamilyOut[]>("/api/families"),
  });

  const create = useMutation({
    mutationFn: () =>
      api<FamilyOut>("/api/families", {
        method: "POST",
        body: JSON.stringify({ name: form.name, reference: form.reference || null }),
      }),
    onSuccess: (family) => {
      setCreating(false);
      setForm({ name: "", reference: "" });
      setOpenId(family.id);
      queryClient.invalidateQueries({ queryKey: ["families"] });
    },
  });

  if (isLoading) {
    return (
      <div className="flex justify-center py-16 text-ink-300">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }

  const term = search.trim().toLowerCase();
  const visible = (families ?? []).filter(
    (family) =>
      !term ||
      family.name.toLowerCase().includes(term) ||
      (family.reference ?? "").toLowerCase().includes(term),
  );

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-ink-900">Familias</h1>
          <p className="mt-1 text-sm text-ink-500">
            Cada reunión se asocia a una familia. De acá salen los reportes.
          </p>
        </div>
        <Button onClick={() => setCreating(true)}>Nueva familia</Button>
      </div>

      {(families ?? []).length > 0 && (
        <Input
          placeholder="Buscar por apellido o legajo…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      )}

      {(families ?? []).length === 0 ? (
        <Card>
          <EmptyState title="Todavía no hay familias" mood="idle">
            <p className="mb-4">
              Creá la primera y cargale sus integrantes. Después vas a poder asociarle reuniones
              y ver todo junto en Reportes.
            </p>
            <Button onClick={() => setCreating(true)}>Nueva familia</Button>
          </EmptyState>
        </Card>
      ) : (
        <div className="space-y-3">
          {visible.map((family) => {
            const guardians = family.members.filter((member) => member.is_guardian).length;
            const open = openId === family.id;
            return (
              <Card key={family.id} className="space-y-3">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h3 className="text-[15px] font-semibold text-ink-900">{family.name}</h3>
                    <p className="mt-0.5 text-sm text-ink-500">
                      {family.reference && <>Legajo {family.reference} · </>}
                      {guardians} {guardians === 1 ? "responsable" : "responsables"} ·{" "}
                      {family.meetings} {family.meetings === 1 ? "reunión" : "reuniones"}
                    </p>
                  </div>
                  <Button
                    variant="soft"
                    onClick={() => setOpenId(open ? null : family.id)}
                  >
                    {open ? "Cerrar" : "Integrantes"}
                  </Button>
                </div>
                {open && <MemberList family={family} />}
              </Card>
            );
          })}
          {visible.length === 0 && (
            <p className="py-8 text-center text-sm text-ink-500">
              Ninguna familia coincide con «{search}».
            </p>
          )}
        </div>
      )}

      <Modal open={creating} onClose={() => setCreating(false)} title="Nueva familia">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (form.name.trim()) create.mutate();
          }}
          className="space-y-4"
        >
          <Input
            label="Nombre"
            placeholder="Familia Gómez"
            required
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
          />
          <Input
            label="Legajo o matrícula (opcional)"
            value={form.reference}
            onChange={(event) => setForm({ ...form, reference: event.target.value })}
          />
          {create.isError && (
            <p className="text-sm text-red-600">
              {create.error instanceof Error ? create.error.message : "No se pudo crear"}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => setCreating(false)}>
              Cancelar
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? <Spinner /> : "Crear"}
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
