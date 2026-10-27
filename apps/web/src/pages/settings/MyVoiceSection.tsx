import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { Switch } from "../../components/Toggles";
import { VOICE_WARNINGS, VoiceRecorder, type MyVoice } from "../../components/VoiceRecorder";
import { Block, Loading } from "./parts";

/**
 * Mi voz: una muestra corta para que, en las reuniones, el transcript diga el
 * nombre de la persona en vez de "Persona 2" (services/speaker_names.py).
 */
export function MyVoiceSection() {
  const queryClient = useQueryClient();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [rerecord, setRerecord] = useState(false);

  const { data: voice, isLoading } = useQuery({
    queryKey: ["my-voice"],
    queryFn: () => api<MyVoice>("/api/me/voice", { skipOrg: true }),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["my-voice"] });
  const remove = useMutation({
    mutationFn: () => api("/api/me/voice", { method: "DELETE", skipOrg: true }),
    onSuccess: () => {
      setConfirmDelete(false);
      return refresh();
    },
  });
  const learning = useMutation({
    mutationFn: (learn: boolean) =>
      api("/api/me/voice", { method: "PATCH", skipOrg: true, body: JSON.stringify({ learn_from_meetings: learn }) }),
    onSuccess: refresh,
  });

  if (isLoading) return <Loading />;

  return (
    <div>
      <Block
        id="voice-actions"
        hint="En el transcript y en el acta aparece tu nombre en lugar de «Persona 1». Se procesa en el servidor de Echo y no se manda a nadie más."
      >
        {voice?.has_sample && (
          <div className="mb-4 rounded-3xl bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
            Tu voz está guardada
            {voice.recorded_at && ` desde el ${new Date(voice.recorded_at).toLocaleDateString("es-AR")}`}.
            {(voice.learned_count ?? 0) > 0 &&
              ` Echo ya la mejoró con ${voice.learned_count} reunión${voice.learned_count === 1 ? "" : "es"}.`}
          </div>
        )}
        {voice?.has_sample && !rerecord && voice.warning && VOICE_WARNINGS[voice.warning] && (
          <div className="mb-4 rounded-3xl bg-amber-50 px-4 py-3 text-sm text-amber-800">
            {VOICE_WARNINGS[voice.warning]}
          </div>
        )}

        {voice?.has_sample && !rerecord ? (
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => setRerecord(true)}
              className="min-h-11 rounded-full bg-ink-100 px-4 text-sm font-medium text-ink-800 hover:bg-ink-200"
            >
              Grabar de nuevo
            </button>
            {confirmDelete ? (
              <span className="flex flex-wrap items-center gap-2 text-sm">
                <span className="text-ink-600">¿Borrar tu voz? Echo deja de reconocerte.</span>
                <button
                  onClick={() => remove.mutate()}
                  disabled={remove.isPending}
                  className="min-h-11 rounded-full bg-red-600 px-4 font-medium text-white hover:bg-red-700"
                >
                  Sí, borrar
                </button>
                <button onClick={() => setConfirmDelete(false)} className="min-h-11 px-3 font-medium text-ink-500">
                  Cancelar
                </button>
              </span>
            ) : (
              <button
                onClick={() => setConfirmDelete(true)}
                className="min-h-11 rounded-full px-4 text-sm font-medium text-red-600 hover:bg-red-50"
              >
                Borrar mi voz
              </button>
            )}
          </div>
        ) : (
          <VoiceRecorder onSaved={() => setRerecord(false)} />
        )}
      </Block>

      {voice?.has_sample && (
        <Block id="voice-learning">
          <Switch
            checked={voice.learn_from_meetings ?? true}
            onChange={(learn) => learning.mutate(learn)}
            label="Mejorar el reconocimiento con mis reuniones"
            hint={
              voice.learn_from_meetings ?? true
                ? "Por ahora Echo no suma reuniones a tu huella: compara solo con tu grabación."
                : "Apagado: Echo usa solo tu grabación. Lo aprendido se olvidó."
            }
          />
        </Block>
      )}
    </div>
  );
}
