import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ReportOut } from "../api/types";
import { Badge, Card, EmptyState, Spinner } from "../components/ui";

/**
 * Reportes por organización.
 *
 * Los gráficos son barras hechas con divs a propósito: son cuatro cortes
 * simples y meter una librería de charts costaría más de lo que aporta.
 */

const SEVERITY_LABEL: Record<string, string> = {
  verde: "Verde",
  amarillo: "Amarillo",
  rojo: "Rojo",
  sin_clasificar: "Sin clasificar",
};

const SEVERITY_BAR: Record<string, string> = {
  verde: "bg-emerald-500",
  amarillo: "bg-amber-400",
  rojo: "bg-red-500",
  sin_clasificar: "bg-ink-200",
};

function monthLabel(month: string): string {
  const [year, m] = month.split("-");
  const names = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  return `${names[Number(m) - 1] ?? m} ${year.slice(2)}`;
}

function Stat({ value, label }: { value: number | string; label: string }) {
  return (
    <Card>
      <p className="text-2xl font-semibold tracking-tight text-ink-900">{value}</p>
      <p className="mt-1 text-sm text-ink-500">{label}</p>
    </Card>
  );
}

function Bar({ value, max, tone }: { value: number; max: number; tone: string }) {
  const width = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 0;
  return (
    <div className="h-2 flex-1 overflow-hidden rounded-full bg-ink-100">
      <div className={`h-full rounded-full ${tone}`} style={{ width: `${width}%` }} />
    </div>
  );
}

export default function Reports() {
  const [months, setMonths] = useState(12);

  const from = new Date();
  from.setMonth(from.getMonth() - months);
  const dateFrom = from.toISOString().slice(0, 10);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["report", dateFrom],
    queryFn: () => api<ReportOut>(`/api/reports/overview?date_from=${dateFrom}`),
  });

  if (isLoading) {
    return (
      <div className="flex justify-center py-16 text-ink-300">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <Card>
        <EmptyState title="No se pudo armar el reporte" mood="error">
          <p>{error instanceof Error ? error.message : "Probá de nuevo en un momento."}</p>
        </EmptyState>
      </Card>
    );
  }

  if (data.totals.meetings === 0) {
    return (
      <div className="space-y-5">
        <h1 className="text-xl font-semibold tracking-tight text-ink-900">Reportes</h1>
        <Card>
          <EmptyState title="Todavía no hay reuniones en este período" mood="idle">
            <p>
              Cuando tengas reuniones clasificadas con familia, motivo y gravedad, acá vas a ver
              cómo se reparten.
            </p>
          </EmptyState>
        </Card>
      </div>
    );
  }

  const maxReason = Math.max(...data.by_reason.map((row) => row.meetings), 1);
  const maxFamily = Math.max(...data.by_family.map((row) => row.meetings), 1);
  const maxMonth = Math.max(...data.timeline.map((row) => row.meetings), 1);
  const attendanceTotal =
    data.attendance.complete + data.attendance.incomplete + data.attendance.unknown;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-ink-900">Reportes</h1>
          <p className="mt-1 text-sm text-ink-500">
            Del {data.range_from} al {data.range_to}
          </p>
        </div>
        <select
          value={months}
          onChange={(event) => setMonths(Number(event.target.value))}
          className="rounded-lg border border-ink-200 px-3 py-2 text-sm"
        >
          <option value={3}>Últimos 3 meses</option>
          <option value={6}>Últimos 6 meses</option>
          <option value={12}>Últimos 12 meses</option>
          <option value={36}>Últimos 3 años</option>
        </select>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat value={data.totals.meetings} label="Reuniones" />
        <Stat value={data.totals.families_with_meetings} label="Familias atendidas" />
        <Stat value={data.totals.classified} label="Clasificadas por completo" />
        <Stat value={data.totals.unclassified} label="Les falta clasificación" />
      </div>

      {data.totals.unclassified > 0 && (
        <div className="rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-800">
          {data.totals.unclassified === 1
            ? "Hay 1 reunión sin familia, motivo o gravedad: no entra en los cortes de abajo."
            : `Hay ${data.totals.unclassified} reuniones sin familia, motivo o gravedad: no entran completas en los cortes de abajo.`}
        </div>
      )}

      {/* ── Evolución en el tiempo ── */}
      <Card className="space-y-4">
        <h2 className="text-[15px] font-semibold text-ink-900">Evolución</h2>
        <div className="flex items-end gap-1.5 overflow-x-auto pb-1">
          {data.timeline.map((row) => (
            <div key={row.month} className="flex min-w-[38px] flex-1 flex-col items-center gap-1.5">
              <span className="text-xs font-medium text-ink-600">{row.meetings}</span>
              <div
                className="flex w-full flex-col-reverse overflow-hidden rounded-t"
                style={{ height: `${Math.max(6, (row.meetings / maxMonth) * 120)}px` }}
                title={`${row.meetings} reuniones`}
              >
                <div className="bg-emerald-500" style={{ flexGrow: row.verde }} />
                <div className="bg-amber-400" style={{ flexGrow: row.amarillo }} />
                <div className="bg-red-500" style={{ flexGrow: row.rojo }} />
                <div
                  className="bg-ink-200"
                  style={{ flexGrow: row.meetings - row.verde - row.amarillo - row.rojo }}
                />
              </div>
              <span className="text-[10px] text-ink-400">{monthLabel(row.month)}</span>
            </div>
          ))}
        </div>
        <div className="flex flex-wrap gap-3 text-xs text-ink-500">
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-emerald-500" /> Verde
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-amber-400" /> Amarillo
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-red-500" /> Rojo
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-ink-200" /> Sin clasificar
          </span>
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* ── Gravedad ── */}
        <Card className="space-y-3">
          <h2 className="text-[15px] font-semibold text-ink-900">Gravedad</h2>
          {(["rojo", "amarillo", "verde", "sin_clasificar"] as const).map((key) => (
            <div key={key} className="flex items-center gap-3">
              <span className="w-24 shrink-0 text-sm text-ink-600">{SEVERITY_LABEL[key]}</span>
              <Bar value={data.by_severity[key]} max={data.totals.meetings} tone={SEVERITY_BAR[key]} />
              <span className="w-8 shrink-0 text-right text-sm tabular-nums text-ink-700">
                {data.by_severity[key]}
              </span>
            </div>
          ))}
        </Card>

        {/* ── Motivos ── */}
        <Card className="space-y-3">
          <h2 className="text-[15px] font-semibold text-ink-900">Motivos</h2>
          {data.by_reason.length === 0 ? (
            <p className="text-sm text-ink-500">Todavía no hay motivos cargados.</p>
          ) : (
            data.by_reason.map((row) => (
              <div key={row.reason_id ?? "sin"} className="flex items-center gap-3">
                <span className="w-32 shrink-0 truncate text-sm text-ink-600" title={row.name}>
                  {row.name}
                </span>
                <Bar value={row.meetings} max={maxReason} tone="bg-accent-500" />
                <span className="w-8 shrink-0 text-right text-sm tabular-nums text-ink-700">
                  {row.meetings}
                </span>
              </div>
            ))
          )}
        </Card>
      </div>

      {/* ── Asistencia ── */}
      <Card className="space-y-4">
        <div>
          <h2 className="text-[15px] font-semibold text-ink-900">Asistencia de los responsables</h2>
          <p className="mt-1 text-sm text-ink-500">
            Sobre {attendanceTotal} {attendanceTotal === 1 ? "reunión" : "reuniones"} con familia
            asignada.
          </p>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="rounded-lg bg-emerald-50 px-4 py-3">
            <p className="text-xl font-semibold text-emerald-700">{data.attendance.complete}</p>
            <p className="text-sm text-emerald-800">Vinieron todos</p>
          </div>
          <div className="rounded-lg bg-amber-50 px-4 py-3">
            <p className="text-xl font-semibold text-amber-700">{data.attendance.incomplete}</p>
            <p className="text-sm text-amber-800">Faltó alguno</p>
          </div>
          <div className="rounded-lg bg-ink-50 px-4 py-3">
            <p className="text-xl font-semibold text-ink-700">{data.attendance.unknown}</p>
            <p className="text-sm text-ink-600">Sin registrar</p>
          </div>
        </div>
        {data.attendance.absentees.length > 0 && (
          <div className="space-y-1.5 border-t border-ink-100 pt-3">
            <p className="text-sm font-medium text-ink-700">Ausencias más frecuentes</p>
            {data.attendance.absentees.map((row) => (
              <div key={row.member_id} className="flex items-center gap-2 text-sm">
                <span className="text-ink-800">{row.name}</span>
                {row.family && <span className="text-ink-400">· {row.family}</span>}
                <span className="ml-auto tabular-nums text-ink-600">
                  {row.missed} {row.missed === 1 ? "ausencia" : "ausencias"}
                </span>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* ── Familias ── */}
      <Card className="space-y-3">
        <h2 className="text-[15px] font-semibold text-ink-900">Reuniones por familia</h2>
        {data.by_family.length === 0 ? (
          <p className="text-sm text-ink-500">
            Ninguna reunión de este período tiene familia asignada.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-ink-100 text-left text-xs uppercase tracking-wide text-ink-400">
                  <th className="py-2 font-medium">Familia</th>
                  <th className="py-2 font-medium">Reuniones</th>
                  <th className="py-2 font-medium">Gravedad</th>
                  <th className="py-2 font-medium">Última</th>
                </tr>
              </thead>
              <tbody>
                {data.by_family.map((row) => (
                  <tr key={row.family_id} className="border-b border-ink-50 last:border-0">
                    <td className="py-2 pr-4 text-ink-800">
                      {row.name}
                      {row.reference && (
                        <span className="ml-1.5 text-xs text-ink-400">{row.reference}</span>
                      )}
                    </td>
                    <td className="py-2 pr-4">
                      <div className="flex items-center gap-2">
                        <Bar value={row.meetings} max={maxFamily} tone="bg-accent-500" />
                        <span className="w-6 tabular-nums text-ink-700">{row.meetings}</span>
                      </div>
                    </td>
                    <td className="py-2 pr-4">
                      <div className="flex gap-1">
                        {row.rojo > 0 && <Badge tone="red">{row.rojo}</Badge>}
                        {row.amarillo > 0 && <Badge tone="amber">{row.amarillo}</Badge>}
                        {row.verde > 0 && <Badge tone="green">{row.verde}</Badge>}
                      </div>
                    </td>
                    <td className="py-2 text-ink-500">
                      {row.last_meeting_at
                        ? new Date(row.last_meeting_at).toLocaleDateString("es")
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
