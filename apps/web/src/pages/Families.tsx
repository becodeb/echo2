import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Tabs } from "../components/Tabs";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { FamilyOut, ProfessionalOut } from "../api/types";
import { LevelBadge } from "../components/FamilyLevel";
import { FamilyImportButton } from "../components/FamilyImport";
import { LEVELS, LEVEL_LABEL, type Level } from "../state/access";
import { Button, Card, EmptyState, Input, Modal, Spinner } from "../components/ui";

/**
 * Familias de la sede. Cada una abre su página (pages/FamilyDetail.tsx); acá
 * se buscan y se filtran por el nivel de sus hijos.
 */

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

type LevelFilter = "" | Level | "sin";

const LEVEL_FILTERS: { value: LevelFilter; label: string }[] = [
  { value: "", label: "Todos" },
  ...LEVELS,
  { value: "sin", label: "Sin nivel" },
];

const normalize = (text: string) =>
  text
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase();

const childrenOf = (family: FamilyOut) =>
  family.members.filter((member) => member.relationship_type === "estudiante");

/** Con un nivel elegido: las familias con algún hijo de ese nivel ("sin": algún hijo sin nivel). */
function matchesLevel(family: FamilyOut, level: LevelFilter): boolean {
  if (!level) return true;
  return childrenOf(family).some((child) => (level === "sin" ? !child.level : child.level === level));
}

function FamilyCard({ family, level, from }: { family: FamilyOut; level: LevelFilter; from: string }) {
  const kids = childrenOf(family);
  const guardians = family.members.filter((member) => member.is_guardian);
  return (
    <Card className="relative p-4 transition-colors hover:border-ink-200 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
        <div className="min-w-0 flex-1">
          {/* Toda la tarjeta abre la familia; el link a Drive queda por encima. */}
          <Link
            to={`/families/${family.id}`}
            state={{ search: from }}
            className="text-[15px] font-semibold text-ink-900 after:absolute after:inset-0 after:rounded-3xl hover:text-accent-600"
          >
            {family.name}
          </Link>
          <p className="mt-0.5 text-sm text-ink-500">
            {family.reference && <>Legajo {family.reference} · </>}
            {guardians.length} {guardians.length === 1 ? "responsable" : "responsables"} ·{" "}
            {family.meetings} {family.meetings === 1 ? "reunión" : "reuniones"}
            {family.assignees.length > 0 &&
              ` · La siguen: ${family.assignees.map((assignee) => assignee.name).join(", ")}`}
          </p>
        </div>
        {family.drive_url && (
          <a
            href={family.drive_url}
            target="_blank"
            rel="noopener noreferrer"
            className="relative z-10 text-sm font-medium text-accent-600 hover:underline"
          >
            Drive ↗
          </a>
        )}
      </div>
      {kids.length > 0 ? (
        <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5">
          {kids.map((child) => {
            const other = level !== "" && !(level === "sin" ? !child.level : child.level === level);
            return (
              <li key={child.id} className={`flex items-center gap-1.5 text-sm ${other ? "opacity-50" : ""}`}>
                <span className="text-ink-800">{child.name}</span>
                {child.curso && <span className="text-xs text-ink-500">{child.curso}</span>}
                <LevelBadge level={child.level} />
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="mt-2 text-xs text-ink-400">Sin hijos cargados</p>
      )}
    </Card>
  );
}

export default function Families() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "profesionales" ? "profesionales" : "familias";
  const rawLevel = params.get("nivel") ?? "";
  const level = (LEVEL_FILTERS.some((item) => item.value === rawLevel) ? rawLevel : "") as LevelFilter;
  const search = params.get("q") ?? "";
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ name: "", reference: "", drive_url: "" });

  // Nivel, búsqueda y pestaña van en la dirección: al volver de una familia siguen igual.
  const setParam = (key: string, value: string) =>
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (value) next.set(key, value);
        else next.delete(key);
        return next;
      },
      { replace: true },
    );
  const from = params.toString() ? `?${params}` : "";

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
      queryClient.invalidateQueries({ queryKey: ["families"] });
      navigate(`/families/${family.id}`, { state: { search: from } });
    },
  });

  const all = families ?? [];
  const term = normalize(search.trim());
  const searched = all.filter(
    (family) =>
      !term ||
      normalize(family.name).includes(term) ||
      normalize(family.reference ?? "").includes(term) ||
      family.members.some((member) => normalize(member.name).includes(term)),
  );
  const visible = searched.filter((family) => matchesLevel(family, level));
  const counts = Object.fromEntries(
    LEVEL_FILTERS.map((item) => [item.value, searched.filter((family) => matchesLevel(family, item.value)).length]),
  ) as Record<LevelFilter, number>;

  return (
    <div className="mx-auto max-w-4xl space-y-5 px-4 py-6 sm:px-6 sm:py-10">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight text-ink-900">Familias</h1>
        {tab === "familias" && (
          <div className="flex flex-wrap gap-2">
            <FamilyImportButton />
            <Button onClick={() => setCreating(true)}>Nueva familia</Button>
          </div>
        )}
      </div>

      <div className="inline-flex">
        <Tabs
          items={[
            { id: "familias", label: "Familias" },
            { id: "profesionales", label: "Profesionales" },
          ]}
          value={tab}
          onChange={(next) => setParam("tab", next === "profesionales" ? next : "")}
          label="Familias o profesionales"
          idPrefix="familias"
        />
      </div>

      <div role="tabpanel" id={`familias-panel-${tab}`} aria-labelledby={`familias-tab-${tab}`}>
        {tab === "profesionales" ? (
          <ProfessionalsTab />
        ) : isLoading ? (
          <div className="flex justify-center py-16 text-ink-300">
            <Spinner className="h-6 w-6" />
          </div>
        ) : all.length === 0 ? (
          <Card>
            <EmptyState title="Todavía no hay familias" mood="idle">
              <p className="mb-4">
                Creá la primera o importá la planilla del colegio. Después vas a poder asociarle reuniones y ver
                todo junto en su página.
              </p>
              <Button onClick={() => setCreating(true)}>Nueva familia</Button>
            </EmptyState>
          </Card>
        ) : (
          <div className="space-y-4">
            <Input
              type="search"
              placeholder="Buscar por apellido, legajo o nombre de un hijo…"
              value={search}
              onChange={(event) => setParam("q", event.target.value)}
            />
            <div role="group" aria-label="Nivel de los hijos" className="flex flex-wrap gap-1.5">
              {LEVEL_FILTERS.filter((item) => item.value !== "sin" || counts.sin > 0 || level === "sin").map(
                (item) => {
                  const active = level === item.value;
                  return (
                    <button
                      key={item.value || "todos"}
                      type="button"
                      aria-pressed={active}
                      onClick={() => setParam("nivel", item.value)}
                      className={`inline-flex min-h-9 items-center gap-1.5 rounded-full border px-3.5 text-sm font-medium transition-colors ${
                        active
                          ? "border-ink-900 bg-ink-900 text-white"
                          : "border-ink-200 bg-white text-ink-600 hover:border-ink-300 hover:text-ink-900"
                      }`}
                    >
                      {item.label}
                      <span className={active ? "text-white/70" : "text-ink-400"}>{counts[item.value]}</span>
                    </button>
                  );
                },
              )}
            </div>
            <div className="space-y-3">
              {visible.map((family) => (
                <FamilyCard key={family.id} family={family} level={level} from={from} />
              ))}
              {visible.length === 0 && (
                <p className="py-8 text-center text-sm text-ink-500">
                  {term
                    ? `Ninguna familia coincide con «${search}»${level ? " en este nivel" : ""}.`
                    : level === "sin"
                      ? "Todos los hijos tienen su nivel."
                      : `Ninguna familia tiene hijos en ${LEVEL_LABEL[level] ?? "este nivel"}.`}
                </p>
              )}
            </div>
          </div>
        )}
      </div>

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
          <p className="text-xs text-ink-400">Los hijos y los responsables se cargan después, en la página de la familia.</p>
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
