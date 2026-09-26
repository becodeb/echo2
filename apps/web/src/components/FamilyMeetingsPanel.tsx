import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { FamilyMeetingOut, FamilyOut, Severity } from "../api/types";
import { LEVEL_LABEL } from "../state/access";
import { AUDIENCES } from "./ClassificationPanel";
import { Select } from "./Select";
import { Badge, EmptyState, Spinner, formatDuration } from "./ui";

/**
 * Panel lateral con todas las reuniones de una familia.
 *
 * Trae todo de una vez (una familia tiene decenas de reuniones, no miles) y
 * filtra acá: fecha, gravedad, motivo, estado del acta, nivel y texto. La
 * visibilidad ya la resolvió el servidor: cada uno ve solo lo que puede ver.
 */

type Period = "todo" | "30d" | "90d" | "anio" | "rango";
type SeverityFilter = Severity | "sin";
type ActaFilter = "" | "draft" | "in_review" | "approved" | "sin";

const PERIODS: { value: Period; label: string }[] = [
  { value: "todo", label: "Todo" },
  { value: "30d", label: "Últimos 30 días" },
  { value: "90d", label: "Últimos 3 meses" },
  { value: "anio", label: "Este año" },
  { value: "rango", label: "Elegir fechas" },
];

const SEVERITY_CHIPS: { value: SeverityFilter; label: string; dot: string }[] = [
  { value: "verde", label: "Verde", dot: "bg-emerald-500" },
  { value: "amarillo", label: "Amarillo", dot: "bg-amber-400" },
  { value: "rojo", label: "Rojo", dot: "bg-red-500" },
  { value: "sin", label: "Sin gravedad", dot: "bg-ink-200" },
];

const SEVERITY_BAR: Record<Severity, string> = {
  verde: "bg-emerald-500",
  amarillo: "bg-amber-400",
  rojo: "bg-red-500",
};

const ACTA_LABEL: Record<string, { label: string; tone: "gray" | "amber" | "green" }> = {
  draft: { label: "Acta en borrador", tone: "gray" },
  in_review: { label: "Acta en revisión", tone: "amber" },
  approved: { label: "Acta aprobada", tone: "green" },
};

const AUDIENCE_LABEL: Record<string, string> = Object.fromEntries(
  AUDIENCES.map((item) => [item.value, item.label]),
);

const DAY = 24 * 60 * 60 * 1000;

const meetingDate = (meeting: FamilyMeetingOut) => new Date(meeting.started_at ?? meeting.created_at);

const normalize = (text: string) =>
  text
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase();

function relative(date: Date): string {
  const days = Math.floor((Date.now() - date.getTime()) / DAY);
  if (days <= 0) return "hoy";
  if (days === 1) return "ayer";
  if (days < 30) return `hace ${days} días`;
  const months = Math.floor(days / 30);
  if (months < 12) return months === 1 ? "hace 1 mes" : `hace ${months} meses`;
  const years = Math.floor(days / 365);
  return years === 1 ? "hace 1 año" : `hace ${years} años`;
}

function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
        active
          ? "border-ink-900 bg-ink-900 text-white"
          : "border-ink-200 bg-white text-ink-600 hover:border-ink-300 hover:text-ink-900"
      }`}
    >
      {children}
    </button>
  );
}

function Stat({ value, label, children }: { value: ReactNode; label: string; children?: ReactNode }) {
  return (
    <div className="min-w-0 rounded-xl border border-ink-100 bg-ink-50/60 px-3 py-2.5">
      <p className="truncate text-lg font-semibold text-ink-900">{value}</p>
      <p className="truncate text-xs text-ink-500">{label}</p>
      {children}
    </div>
  );
}

function MeetingRow({ meeting }: { meeting: FamilyMeetingOut }) {
  const date = meetingDate(meeting);
  const acta = meeting.minutes_status ? ACTA_LABEL[meeting.minutes_status] : null;
  return (
    <li>
      <Link
        to={`/meetings/${meeting.id}`}
        className="group flex gap-3 rounded-xl border border-ink-100 bg-white p-3.5 transition-colors hover:border-ink-200 hover:bg-ink-50/50"
      >
        <span
          aria-hidden
          className={`w-1 shrink-0 rounded-full ${meeting.severity ? SEVERITY_BAR[meeting.severity] : "bg-ink-100"}`}
        />
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
            <p className="min-w-0 break-words text-[15px] font-medium text-ink-900 group-hover:text-accent-600">
              {meeting.title}
            </p>
            <p className="shrink-0 text-xs text-ink-500">
              {date.toLocaleDateString("es", { weekday: "short", day: "numeric", month: "short" })}
              {meeting.duration_seconds > 0 && ` · ${formatDuration(meeting.duration_seconds)}`}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            {meeting.reason_name && <Badge tone="indigo">{meeting.reason_name}</Badge>}
            {acta && (
              <Badge tone={acta.tone}>
                {acta.label}
                {meeting.minutes_number != null && ` · Nº ${meeting.minutes_number}`}
              </Badge>
            )}
            {meeting.status === "live" && <Badge tone="red">En curso</Badge>}
            {meeting.audience && <Badge tone="gray">{AUDIENCE_LABEL[meeting.audience] ?? meeting.audience}</Badge>}
            {meeting.level && <Badge tone="gray">{LEVEL_LABEL[meeting.level] ?? meeting.level}</Badge>}
          </div>

          {(meeting.all_guardians_present !== null || meeting.professionals.length > 0) && (
            <p className="text-xs text-ink-500">
              {meeting.all_guardians_present === true && (
                <span className="text-emerald-700">Vinieron todos los responsables</span>
              )}
              {meeting.all_guardians_present === false && (
                <span className="text-amber-700">
                  Faltó algún responsable
                  {meeting.attended.length > 0 && ` (vino ${meeting.attended.join(", ")})`}
                </span>
              )}
              {meeting.all_guardians_present !== null && meeting.professionals.length > 0 && " · "}
              {meeting.professionals.length > 0 && <>Con {meeting.professionals.join(", ")}</>}
            </p>
          )}

          {meeting.summary.length > 0 && (
            <ul className="space-y-0.5 text-sm text-ink-600">
              {meeting.summary.slice(0, 2).map((point, index) => (
                <li key={index} className="flex gap-1.5">
                  <span aria-hidden className="text-ink-300">•</span>
                  <span className="min-w-0 break-words">{point}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Link>
    </li>
  );
}

export function FamilyMeetingsPanel({ family, onClose }: { family: FamilyOut; onClose: () => void }) {
  const [search, setSearch] = useState("");
  const [period, setPeriod] = useState<Period>("todo");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [severities, setSeverities] = useState<Set<SeverityFilter>>(new Set());
  const [reasonId, setReasonId] = useState("");
  const [acta, setActa] = useState<ActaFilter>("");
  const [level, setLevel] = useState("");
  const [order, setOrder] = useState<"desc" | "asc">("desc");

  const { data: meetings, isLoading, isError } = useQuery({
    queryKey: ["family-meetings", family.id],
    queryFn: () => api<FamilyMeetingOut[]>(`/api/families/${family.id}/meetings`),
  });

  // Escape cierra y la página de atrás no scrollea mientras el panel está abierto.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [onClose]);

  const all = meetings ?? [];

  const reasonOptions = useMemo(() => {
    const counts = new Map<string, { name: string; count: number }>();
    for (const meeting of all) {
      if (!meeting.reason_id) continue;
      const entry = counts.get(meeting.reason_id) ?? { name: meeting.reason_name ?? "—", count: 0 };
      entry.count += 1;
      counts.set(meeting.reason_id, entry);
    }
    return [
      { value: "", label: "Todos los motivos" },
      ...[...counts.entries()]
        .sort((a, b) => b[1].count - a[1].count)
        .map(([value, entry]) => ({ value, label: entry.name, hint: String(entry.count) })),
      ...(all.some((meeting) => !meeting.reason_id) ? [{ value: "sin", label: "Sin motivo" }] : []),
    ];
  }, [all]);

  const levels = useMemo(
    () => [...new Set(all.map((meeting) => meeting.level).filter(Boolean))] as string[],
    [all],
  );

  const filtered = useMemo(() => {
    const now = Date.now();
    let start: number | null = null;
    let end: number | null = null;
    if (period === "30d") start = now - 30 * DAY;
    if (period === "90d") start = now - 90 * DAY;
    if (period === "anio") start = new Date(new Date().getFullYear(), 0, 1).getTime();
    if (period === "rango") {
      if (from) start = new Date(`${from}T00:00:00`).getTime();
      if (to) end = new Date(`${to}T23:59:59.999`).getTime();
    }
    const term = normalize(search.trim());

    const rows = all.filter((meeting) => {
      const time = meetingDate(meeting).getTime();
      if (start !== null && time < start) return false;
      if (end !== null && time > end) return false;
      if (severities.size > 0 && !severities.has(meeting.severity ?? "sin")) return false;
      if (reasonId === "sin" ? meeting.reason_id !== null : reasonId && meeting.reason_id !== reasonId) {
        return false;
      }
      if (acta === "sin" ? meeting.minutes_status !== null : acta && meeting.minutes_status !== acta) {
        return false;
      }
      if (level && meeting.level !== level) return false;
      if (term) {
        const haystack = normalize(
          [
            meeting.title,
            meeting.reason_name ?? "",
            ...meeting.summary,
            ...meeting.attended,
            ...meeting.professionals,
          ].join(" "),
        );
        if (!haystack.includes(term)) return false;
      }
      return true;
    });
    return order === "asc" ? [...rows].reverse() : rows;
  }, [all, period, from, to, severities, reasonId, acta, level, search, order]);

  const groups = useMemo(() => {
    const out: { key: string; label: string; items: FamilyMeetingOut[] }[] = [];
    for (const meeting of filtered) {
      const date = meetingDate(meeting);
      const key = `${date.getFullYear()}-${date.getMonth()}`;
      let group = out[out.length - 1];
      if (!group || group.key !== key) {
        const label = date.toLocaleDateString("es", { month: "long", year: "numeric" });
        group = { key, label: label[0].toUpperCase() + label.slice(1), items: [] };
        out.push(group);
      }
      group.items.push(meeting);
    }
    return out;
  }, [filtered]);

  const stats = useMemo(() => {
    const bySeverity = { verde: 0, amarillo: 0, rojo: 0 };
    let recorded = 0;
    let complete = 0;
    for (const meeting of filtered) {
      if (meeting.severity) bySeverity[meeting.severity] += 1;
      if (meeting.all_guardians_present !== null) {
        recorded += 1;
        if (meeting.all_guardians_present) complete += 1;
      }
    }
    const latest = filtered.reduce<Date | null>((best, meeting) => {
      const date = meetingDate(meeting);
      return !best || date > best ? date : best;
    }, null);
    return { bySeverity, recorded, complete, latest };
  }, [filtered]);

  const filtersActive =
    search.trim() !== "" ||
    period !== "todo" ||
    severities.size > 0 ||
    reasonId !== "" ||
    acta !== "" ||
    level !== "";

  const clear = () => {
    setSearch("");
    setPeriod("todo");
    setFrom("");
    setTo("");
    setSeverities(new Set());
    setReasonId("");
    setActa("");
    setLevel("");
  };

  const toggleSeverity = (value: SeverityFilter) =>
    setSeverities((current) => {
      const next = new Set(current);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      return next;
    });

  const severityTotal = stats.bySeverity.verde + stats.bySeverity.amarillo + stats.bySeverity.rojo;
  const guardians = family.members.filter((member) => member.is_guardian);

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-ink-950/40 backdrop-blur-[2px]"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-label={`Reuniones de ${family.name}`}
    >
      <aside className="animate-slide-in flex h-full w-full max-w-2xl flex-col bg-white shadow-2xl">
        {/* Encabezado */}
        <header className="border-b border-ink-100 px-4 py-4 sm:px-6">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-xs font-medium uppercase tracking-wide text-ink-400">Reuniones de la familia</p>
              <h2 className="break-words text-xl font-semibold text-ink-900">{family.name}</h2>
              <p className="mt-0.5 text-sm text-ink-500">
                {family.reference && <>Legajo {family.reference} · </>}
                {guardians.length > 0
                  ? guardians.map((member) => member.name).join(", ")
                  : "Sin responsables cargados"}
                {family.drive_url && (
                  <>
                    {" · "}
                    <a
                      href={family.drive_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-medium text-accent-600 hover:underline"
                    >
                      Drive ↗
                    </a>
                  </>
                )}
              </p>
            </div>
            <button
              onClick={onClose}
              className="shrink-0 rounded-lg p-2 text-ink-400 hover:bg-ink-100 hover:text-ink-700"
              aria-label="Cerrar"
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
            </button>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto overflow-x-hidden px-4 py-4 sm:px-6">
          {isLoading ? (
            <div className="flex justify-center py-16 text-ink-300">
              <Spinner className="h-6 w-6" />
            </div>
          ) : isError ? (
            <p className="py-10 text-center text-sm text-red-600">No se pudieron cargar las reuniones.</p>
          ) : all.length === 0 ? (
            <EmptyState title="Todavía no hay reuniones con esta familia" mood="idle">
              <p>
                Cuando una reunión se clasifica con esta familia (en el detalle de la reunión, o al
                crearla), aparece acá.
              </p>
            </EmptyState>
          ) : (
            <div className="space-y-5">
              {/* Números del período filtrado */}
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Stat value={filtered.length} label={filtered.length === 1 ? "reunión" : "reuniones"} />
                <Stat
                  value={stats.latest ? relative(stats.latest) : "—"}
                  label="última reunión"
                />
                <Stat
                  value={stats.recorded ? `${stats.complete} de ${stats.recorded}` : "—"}
                  label="asistencia completa"
                />
                <Stat value={stats.bySeverity.rojo} label="en rojo">
                  {severityTotal > 0 && (
                    <div className="mt-1.5 flex h-1.5 overflow-hidden rounded-full bg-ink-100">
                      <div className="bg-emerald-500" style={{ flexGrow: stats.bySeverity.verde }} />
                      <div className="bg-amber-400" style={{ flexGrow: stats.bySeverity.amarillo }} />
                      <div className="bg-red-500" style={{ flexGrow: stats.bySeverity.rojo }} />
                    </div>
                  )}
                </Stat>
              </div>

              {/* Filtros */}
              <div className="space-y-3 rounded-xl border border-ink-100 p-3">
                <input
                  type="search"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Buscar en títulos, motivos, resúmenes y asistentes…"
                  className="w-full rounded-lg border border-ink-200 bg-white px-3 py-2 text-base text-ink-900 placeholder:text-ink-400 sm:text-sm focus:border-accent-500 focus:outline-none focus:ring-2 focus:ring-accent-500/20"
                />

                <div className="flex flex-wrap gap-1.5">
                  {PERIODS.map((item) => (
                    <Chip key={item.value} active={period === item.value} onClick={() => setPeriod(item.value)}>
                      {item.label}
                    </Chip>
                  ))}
                </div>
                {period === "rango" && (
                  <div className="grid grid-cols-2 gap-2">
                    <label className="block min-w-0">
                      <span className="mb-1 block text-xs font-medium text-ink-600">Desde</span>
                      <input
                        type="date"
                        value={from}
                        max={to || undefined}
                        onChange={(event) => setFrom(event.target.value)}
                        className="w-full min-w-0 rounded-lg border border-ink-200 bg-white px-2.5 py-1.5 text-base text-ink-900 sm:text-sm focus:border-accent-500 focus:outline-none"
                      />
                    </label>
                    <label className="block min-w-0">
                      <span className="mb-1 block text-xs font-medium text-ink-600">Hasta</span>
                      <input
                        type="date"
                        value={to}
                        min={from || undefined}
                        onChange={(event) => setTo(event.target.value)}
                        className="w-full min-w-0 rounded-lg border border-ink-200 bg-white px-2.5 py-1.5 text-base text-ink-900 sm:text-sm focus:border-accent-500 focus:outline-none"
                      />
                    </label>
                  </div>
                )}

                <div className="flex flex-wrap gap-1.5">
                  {SEVERITY_CHIPS.map((item) => (
                    <Chip
                      key={item.value}
                      active={severities.has(item.value)}
                      onClick={() => toggleSeverity(item.value)}
                    >
                      <span aria-hidden className={`h-2 w-2 rounded-full ${item.dot}`} />
                      {item.label}
                    </Chip>
                  ))}
                </div>

                <div className="grid gap-2 sm:grid-cols-2">
                  <Select
                    ariaLabel="Motivo"
                    size="sm"
                    value={reasonId}
                    onChange={setReasonId}
                    options={reasonOptions}
                    searchPlaceholder="Buscar motivo…"
                  />
                  <Select
                    ariaLabel="Estado del acta"
                    size="sm"
                    value={acta}
                    onChange={(value) => setActa(value as ActaFilter)}
                    options={[
                      { value: "", label: "Todas las actas" },
                      { value: "draft", label: "Acta en borrador" },
                      { value: "in_review", label: "Acta en revisión" },
                      { value: "approved", label: "Acta aprobada" },
                      { value: "sin", label: "Sin acta" },
                    ]}
                  />
                  {levels.length > 1 && (
                    <Select
                      ariaLabel="Nivel"
                      size="sm"
                      value={level}
                      onChange={setLevel}
                      options={[
                        { value: "", label: "Todos los niveles" },
                        ...levels.map((value) => ({ value, label: LEVEL_LABEL[value] ?? value })),
                      ]}
                    />
                  )}
                  <Select
                    ariaLabel="Orden"
                    size="sm"
                    value={order}
                    onChange={(value) => setOrder(value as "desc" | "asc")}
                    options={[
                      { value: "desc", label: "Más nuevas primero" },
                      { value: "asc", label: "Más viejas primero" },
                    ]}
                  />
                </div>

                <div className="flex items-center justify-between gap-2 text-xs text-ink-500">
                  <span>
                    {filtered.length === all.length
                      ? `${all.length} ${all.length === 1 ? "reunión" : "reuniones"}`
                      : `${filtered.length} de ${all.length} reuniones`}
                  </span>
                  {filtersActive && (
                    <button onClick={clear} className="font-medium text-accent-600 hover:underline">
                      Limpiar filtros
                    </button>
                  )}
                </div>
              </div>

              {/* Lista agrupada por mes */}
              {filtered.length === 0 ? (
                <p className="py-10 text-center text-sm text-ink-500">
                  Ninguna reunión coincide con los filtros.{" "}
                  <button onClick={clear} className="font-medium text-accent-600 hover:underline">
                    Limpiar
                  </button>
                </p>
              ) : (
                <div className="space-y-5">
                  {groups.map((group) => (
                    <section key={group.key} className="space-y-2">
                      <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-400">
                        {group.label}
                      </h3>
                      <ul className="space-y-2">
                        {group.items.map((meeting) => (
                          <MeetingRow key={meeting.id} meeting={meeting} />
                        ))}
                      </ul>
                    </section>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
