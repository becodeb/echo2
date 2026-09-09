import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { FamilyMemberOut, FamilyOut, ProfessionalOut } from "../api/types";
import { Badge, Button, Card, EmptyState, Input, Modal, Spinner } from "../components/ui";

const RELATIONSHIPS: FamilyMemberOut["relationship_type"][] = [
  "madre",
  "padre",
  "tutor",
  "estudiante",
  "otro",
];

// ── Detalle de una familia ───────────────────────────────────────

function FamilyDetail({ family }: { family: FamilyOut }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [relationship, setRelationship] =
    useState<FamilyMemberOut["relationship_type"]>("madre");
  const [drive, setDrive] = useState(family.drive_url ?? "");
  const [linking, setLinking] = useState("");

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["families"] });

  const { data: professionals } = useQuery({
    queryKey: ["professionals"],
    queryFn: () => api<ProfessionalOut[]>("/api/professionals"),
  });

  const addMember = useMutation({
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

  const removeMember = useMutation({
    mutationFn: (memberId: string) =>
      api(`/api/families/members/${memberId}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });

  const saveDrive = useMutation({
    mutationFn: () =>
      api<FamilyOut>(`/api/families/${family.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: family.name,
          reference: family.reference,
          notes: family.notes,
          drive_url: drive || null,
        }),
      }),
    onSuccess: invalidate,
  });

  const linkPro = useMutation({
    mutationFn: (professionalId: string) =>
      api(`/api/families/${family.id}/professionals/${professionalId}`, { method: "PUT" }),
    onSuccess: () => {
      setLinking("");
      invalidate();
    },
  });

  const unlinkPro = useMutation({
    mutationFn: (professionalId: string) =>
      api(`/api/families/${family.id}/professionals/${professionalId}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });

  const linkedIds = new Set(family.professionals.map((pro) => pro.id));
  const available = (professionals ?? []).filter((pro) => !linkedIds.has(pro.id));

  return (
    <div className="space-y-5 border-t border-ink-100 pt-4">
      {/* Carpeta de Drive */}
      <div>
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-[220px] flex-1">
            <Input
              label="Carpeta de Drive"
              placeholder="https://drive.google.com/drive/folders/…"
              value={drive}
              onChange={(event) => setDrive(event.target.value)}
            />
          </div>
          <Button variant="soft" onClick={() => saveDrive.mutate()} disabled={saveDrive.isPending}>
            {saveDrive.isPending ? <Spinner /> : "Guardar"}
          </Button>
          {family.drive_url && (
            <a
              href={family.drive_url}
              target="_blank"
              rel="noopener noreferrer"
              className="pb-2 text-sm font-medium text-accent-600 hover:underline"
            >
              Abrir ↗
            </a>
          )}
        </div>
        <p className="mt-1 text-xs text-ink-400">
          Echo guarda el enlace, no el contenido: los informes y el contexto siguen viviendo en tu
          Drive. El enlace aparece en cada reunión de esta familia.
        </p>
      </div>

      {/* Integrantes */}
      <div className="space-y-2">
        <span className="block text-sm font-medium text-ink-700">Integrantes</span>
        {family.members.length === 0 ? (
          <p className="text-sm text-ink-500">
            Cargá al menos a los responsables: son contra quienes se mide si vinieron todos.
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
                  onClick={() => removeMember.mutate(member.id)}
                  className="ml-auto text-xs text-ink-400 hover:text-red-600"
                >
                  Quitar
                </button>
              </li>
            ))}
          </ul>
        )}

        <form
          onSubmit={(event: FormEvent) => {
            event.preventDefault();
            if (name.trim()) addMember.mutate();
          }}
          className="flex flex-wrap items-end gap-2"
        >
          <div className="min-w-[160px] flex-1">
            <Input
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
          <Button type="submit" variant="soft" disabled={addMember.isPending}>
            {addMember.isPending ? <Spinner /> : "Agregar"}
          </Button>
        </form>
      </div>

      {/* Profesionales que la acompañan */}
      <div className="space-y-2">
        <span className="block text-sm font-medium text-ink-700">Profesionales que acompañan</span>
        {family.professionals.length === 0 ? (
          <p className="text-sm text-ink-500">Ninguno asociado todavía.</p>
        ) : (
          <ul className="space-y-1.5">
            {family.professionals.map((pro) => (
              <li key={pro.id} className="flex items-center gap-2 text-sm">
                <span className="text-ink-800">{pro.name}</span>
                {pro.role_label && <Badge tone="gray">{pro.role_label}</Badge>}
                <button
                  onClick={() => unlinkPro.mutate(pro.id)}
                  className="ml-auto text-xs text-ink-400 hover:text-red-600"
                >
                  Desasociar
                </button>
              </li>
            ))}
          </ul>
        )}
        {available.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={linking}
              onChange={(event) => setLinking(event.target.value)}
              className="rounded-lg border border-ink-200 px-3 py-2 text-sm"
            >
              <option value="">— elegir profesional —</option>
              {available.map((pro) => (
                <option key={pro.id} value={pro.id}>
                  {pro.name}
                  {pro.role_label ? ` · ${pro.role_label}` : ""}
                </option>
              ))}
            </select>
            <Button
              variant="soft"
              onClick={() => linking && linkPro.mutate(linking)}
              disabled={!linking || linkPro.isPending}
            >
              Asociar
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Directorio de profesionales ──────────────────────────────────

function ProfessionalsTab() {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ name: "", role_label: "", affiliation: "", email: "", phone: "" });
  const [creating, setCreating] = useState(false);

  const { data: professionals, isLoading } = useQuery({
    queryKey: ["professionals"],
    queryFn: () => api<ProfessionalOut[]>("/api/professionals"),
  });

  const create = useMutation({
    mutationFn: () =>
      api<ProfessionalOut>("/api/professionals", {
        method: "POST",
        body: JSON.stringify({ ...form, is_active: true }),
      }),
    onSuccess: () => {
      setForm({ name: "", role_label: "", affiliation: "", email: "", phone: "" });
      setCreating(false);
      queryClient.invalidateQueries({ queryKey: ["professionals"] });
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/professionals/${id}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["professionals"] }),
  });

  if (isLoading) {
    return (
      <div className="flex justify-center py-16 text-ink-300">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-ink-500">
          Terapeutas, acompañantes y docentes externos. Se cargan una vez y se asocian a las
          familias que acompañan.
        </p>
        <Button onClick={() => setCreating(true)}>Nuevo profesional</Button>
      </div>

      {(professionals ?? []).length === 0 ? (
        <Card>
          <EmptyState title="Todavía no hay profesionales" mood="idle">
            <p className="mb-4">
              Cargá al primero y después vas a poder asociarlo a las familias y marcarlo como
              presente en las reuniones.
            </p>
            <Button onClick={() => setCreating(true)}>Nuevo profesional</Button>
          </EmptyState>
        </Card>
      ) : (
        <div className="space-y-2">
          {(professionals ?? []).map((pro) => (
            <Card key={pro.id} className="flex flex-wrap items-center gap-3">
              <div>
                <p className="text-[15px] font-medium text-ink-900">{pro.name}</p>
                <p className="text-sm text-ink-500">
                  {[pro.role_label, pro.affiliation, pro.email, pro.phone]
                    .filter(Boolean)
                    .join(" · ") || "Sin datos de contacto"}
                </p>
              </div>
              <button
                onClick={() => remove.mutate(pro.id)}
                className="ml-auto text-sm text-ink-400 hover:text-red-600"
              >
                Quitar
              </button>
            </Card>
          ))}
        </div>
      )}

      <Modal open={creating} onClose={() => setCreating(false)} title="Nuevo profesional">
        <form
          onSubmit={(event: FormEvent) => {
            event.preventDefault();
            if (form.name.trim()) create.mutate();
          }}
          className="space-y-4"
        >
          <Input
            label="Nombre"
            required
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
          />
          <Input
            label="Rol"
            placeholder="Terapeuta ocupacional, psicopedagoga, fonoaudióloga…"
            value={form.role_label}
            onChange={(event) => setForm({ ...form, role_label: event.target.value })}
          />
          <Input
            label="Institución (opcional)"
            value={form.affiliation}
            onChange={(event) => setForm({ ...form, affiliation: event.target.value })}
          />
          <div className="grid gap-4 sm:grid-cols-2">
            <Input
              label="Email"
              type="email"
              value={form.email}
              onChange={(event) => setForm({ ...form, email: event.target.value })}
            />
            <Input
              label="Teléfono"
              value={form.phone}
              onChange={(event) => setForm({ ...form, phone: event.target.value })}
            />
          </div>
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

// ── Página ───────────────────────────────────────────────────────

export default function Families() {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<"familias" | "profesionales">("familias");
  const [creating, setCreating] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", reference: "", drive_url: "" });
  const [search, setSearch] = useState("");

  const { data: families, isLoading } = useQuery({
    queryKey: ["families"],
    queryFn: () => api<FamilyOut[]>("/api/families"),
  });

  const create = useMutation({
    mutationFn: () =>
      api<FamilyOut>("/api/families", {
        method: "POST",
        body: JSON.stringify({
          name: form.name,
          reference: form.reference || null,
          drive_url: form.drive_url || null,
        }),
      }),
    onSuccess: (family) => {
      setCreating(false);
      setForm({ name: "", reference: "", drive_url: "" });
      setOpenId(family.id);
      queryClient.invalidateQueries({ queryKey: ["families"] });
    },
  });

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
        <h1 className="text-xl font-semibold tracking-tight text-ink-900">Familias</h1>
        {tab === "familias" && <Button onClick={() => setCreating(true)}>Nueva familia</Button>}
      </div>

      <div className="flex gap-1 border-b border-ink-100">
        {(["familias", "profesionales"] as const).map((item) => (
          <button
            key={item}
            onClick={() => setTab(item)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium capitalize ${
              tab === item
                ? "border-ink-900 text-ink-900"
                : "border-transparent text-ink-500 hover:text-ink-800"
            }`}
          >
            {item}
          </button>
        ))}
      </div>

      {tab === "profesionales" ? (
        <ProfessionalsTab />
      ) : isLoading ? (
        <div className="flex justify-center py-16 text-ink-300">
          <Spinner className="h-6 w-6" />
        </div>
      ) : (families ?? []).length === 0 ? (
        <Card>
          <EmptyState title="Todavía no hay familias" mood="idle">
            <p className="mb-4">
              Creá la primera y cargale sus integrantes. Después vas a poder asociarle reuniones y
              ver todo junto en Reportes.
            </p>
            <Button onClick={() => setCreating(true)}>Nueva familia</Button>
          </EmptyState>
        </Card>
      ) : (
        <>
          <Input
            placeholder="Buscar por apellido o legajo…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
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
                        {family.professionals.length > 0 &&
                          ` · ${family.professionals.length} prof.`}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      {family.drive_url && (
                        <a
                          href={family.drive_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-sm font-medium text-accent-600 hover:underline"
                        >
                          Drive ↗
                        </a>
                      )}
                      <Button variant="soft" onClick={() => setOpenId(open ? null : family.id)}>
                        {open ? "Cerrar" : "Detalle"}
                      </Button>
                    </div>
                  </div>
                  {open && <FamilyDetail family={family} />}
                </Card>
              );
            })}
            {visible.length === 0 && (
              <p className="py-8 text-center text-sm text-ink-500">
                Ninguna familia coincide con «{search}».
              </p>
            )}
          </div>
        </>
      )}

      <Modal open={creating} onClose={() => setCreating(false)} title="Nueva familia">
        <form
          onSubmit={(event: FormEvent) => {
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
          <Input
            label="Carpeta de Drive (opcional)"
            placeholder="https://drive.google.com/drive/folders/…"
            value={form.drive_url}
            onChange={(event) => setForm({ ...form, drive_url: event.target.value })}
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
