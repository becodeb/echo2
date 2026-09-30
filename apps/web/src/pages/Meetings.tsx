import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { MeetingListItem } from "../api/types";
import { MeetingList } from "../components/MeetingList";
import { NewMeetingModal } from "../components/NewMeetingModal";
import { Button, Card, EmptyState, Spinner } from "../components/ui";
import { useAuth } from "../state/auth";

export default function Meetings() {
  const { activeOrg } = useAuth();
  const [params, setParams] = useSearchParams();
  const [showNew, setShowNew] = useState(params.get("new") === "1");

  useEffect(() => {
    if (params.get("new") === "1") setShowNew(true);
  }, [params]);

  const { data: meetings, isLoading } = useQuery({
    queryKey: ["meetings", activeOrg?.id, "familia"],
    // Las internas tienen su sección (pages/InternalMeetings.tsx).
    queryFn: () => api<MeetingListItem[]>("/api/meetings?kind=familia"),
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

      {meetings && meetings.length > 0 && <MeetingList meetings={meetings} />}

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
