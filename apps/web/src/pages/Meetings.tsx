import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { FamilyOut } from "../api/types";
import { MeetingList } from "../components/MeetingList";
import { NewMeetingModal } from "../components/NewMeetingModal";
import { Select } from "../components/Select";
import { Button, Card, EmptyState, Spinner } from "../components/ui";
import { useAuth } from "../state/auth";
import { LEVELS } from "../state/access";
import { useMeetingPages } from "../lib/meetingPages";

const ACTAS = [
  { value: "", label: "Todas las actas" },
  { value: "pending", label: "Por confirmar" },
  { value: "approved", label: "Aprobada" },
  { value: "none", label: "Sin acta" },
];

export default function Meetings() {
  const { activeOrg } = useAuth();
  const [params, setParams] = useSearchParams();
  const [showNew, setShowNew] = useState(params.get("new") === "1");

  useEffect(() => {
    if (params.get("new") === "1") setShowNew(true);
  }, [params]);

  // Los filtros viven en la dirección: al volver de una reunión la lista queda como estaba.
  const familyId = params.get("familia") ?? "";
  const level = params.get("nivel") ?? "";
  const acta = params.get("acta") ?? "";
  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };
  const filtered = Boolean(familyId || level || acta);
  const clear = () => {
    const next = new URLSearchParams(params);
    ["familia", "nivel", "acta"].forEach((key) => next.delete(key));
    setParams(next, { replace: true });
  };

  const { data: families } = useQuery({
    queryKey: ["families"],
    queryFn: () => api<FamilyOut[]>("/api/families"),
    enabled: !!activeOrg,
  });
  const familyOptions = useMemo(
    () => [{ value: "", label: "Todas las familias" }, ...(families ?? []).map((family) => ({ value: family.id, label: family.name }))],
    [families],
  );

  // Las internas tienen su sección (pages/InternalMeetings.tsx).
  const query = new URLSearchParams({ kind: "familia" });
  if (familyId) query.set("family_id", familyId);
  if (level) query.set("level", level);
  if (acta) query.set("minutes", acta);
  const { meetings, isLoading, hasNextPage, fetchNextPage, isFetchingNextPage } = useMeetingPages(
    ["meetings", activeOrg?.id, "familia", familyId, level, acta],
    `/api/meetings?${query}`,
    !!activeOrg,
  );

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 sm:px-6 sm:py-10">
      <div className="mb-5 flex items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight text-ink-900">Reuniones</h1>
        <Button onClick={() => setShowNew(true)}>+ Nueva reunión</Button>
      </div>

      <div className="mb-5 grid grid-cols-2 gap-2 sm:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)_minmax(0,1fr)]">
        <Select
          ariaLabel="Familia"
          size="sm"
          searchable
          searchPlaceholder="Buscar familia…"
          className="col-span-2 sm:col-span-1"
          value={familyId}
          onChange={(value) => setFilter("familia", value)}
          options={familyOptions}
        />
        <Select
          ariaLabel="Nivel"
          size="sm"
          value={level}
          onChange={(value) => setFilter("nivel", value)}
          options={[{ value: "", label: "Todos los niveles" }, ...LEVELS]}
        />
        <Select ariaLabel="Estado del acta" size="sm" value={acta} onChange={(value) => setFilter("acta", value)} options={ACTAS} />
      </div>

      {isLoading && (
        <div className="flex justify-center py-16 text-ink-400">
          <Spinner className="h-6 w-6" />
        </div>
      )}

      {meetings && meetings.length === 0 && filtered && (
        <p className="py-12 text-center text-sm text-ink-500">
          Ninguna reunión coincide con los filtros.{" "}
          <button onClick={clear} className="font-medium text-accent-600 hover:underline">
            Limpiar
          </button>
        </p>
      )}

      {meetings && meetings.length === 0 && !filtered && (
        <Card>
          <EmptyState title="Todavía no hay reuniones" mood="idle">
            Tocá «Nueva reunión», elegí tu micrófono y Echo escucha, transcribe y arma el acta por vos.
          </EmptyState>
        </Card>
      )}

      {meetings && meetings.length > 0 && (
        <>
          {filtered && (
            <p className="-mt-2 mb-3 text-xs text-ink-500">
              <button onClick={clear} className="font-medium text-accent-600 hover:underline">
                Limpiar filtros
              </button>
            </p>
          )}
          <MeetingList meetings={meetings} hasMore={hasNextPage} loadingMore={isFetchingNextPage} onMore={() => fetchNextPage()} />
        </>
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
