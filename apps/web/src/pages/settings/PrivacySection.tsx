import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { Spinner } from "../../components/ui";
import { Block, ErrorText } from "./parts";

/** Tus datos: cómo los cuida Echo, y pedir una copia, corregirlos o la baja (Ley 25.326). */
export function PrivacySection() {
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const { data: deletion } = useQuery({
    queryKey: ["deletion-request"],
    queryFn: () => api<{ requested_at: string | null }>("/api/me/deletion-request", { skipOrg: true }),
  });
  const ask = useMutation({
    mutationFn: () => api("/api/me/deletion-request", { method: "POST", skipOrg: true }),
    onSuccess: () => {
      setConfirming(false);
      return queryClient.invalidateQueries({ queryKey: ["deletion-request"] });
    },
  });

  return (
    <div>
      <Block id="privacy-how" title="Cómo cuida Echo tus datos">
        <ul className="space-y-2.5 text-sm leading-relaxed text-ink-600">
          <li>
            <strong className="text-ink-800">El audio no queda guardado.</strong> Echo usa una copia de trabajo para
            transcribir y la borra al terminar (si algo falla, como mucho 48 horas). Solo si elegís grabar una reunión,
            el audio va a tu Google Drive.
          </li>
          <li>
            <strong className="text-ink-800">Los nombres no le llegan a la IA:</strong> se reemplazan por marcadores
            antes de redactar el acta o responder, y vuelven al terminar.
          </li>
          <li>
            <strong className="text-ink-800">Reuniones con menores:</strong> no se separa quién habló y la voz de Echo
            no las usa.
          </li>
          <li>
            <strong className="text-ink-800">Siempre se ve cuándo se graba:</strong> la app y el Echo Device muestran
            «● Grabando». Avisá a quienes participan que la reunión se transcribe.
          </li>
        </ul>
        <p className="mt-4 text-sm">
          <Link to="/legal/privacidad" className="font-medium text-ink-900 underline underline-offset-2">
            Leer la política de privacidad completa
          </Link>
        </p>
      </Block>

      <Block
        id="privacy-requests"
        title="Pedir tus datos o borrarlos"
        hint="Podés pedir una copia de tus datos, corregirlos o borrarlos (Ley 25.326)."
      >
        <div className="flex flex-wrap gap-2">
          <Link
            to="/contacto?tema=privacidad"
            className="inline-flex min-h-11 items-center rounded-full bg-ink-100 px-4 text-sm font-medium text-ink-800 hover:bg-ink-200"
          >
            Pedir mis datos o corregirlos
          </Link>
          {!deletion?.requested_at && !confirming && (
            <button
              onClick={() => setConfirming(true)}
              className="min-h-11 rounded-full px-4 text-sm font-medium text-red-600 hover:bg-red-50"
            >
              Pedir la baja de mi cuenta
            </button>
          )}
        </div>
        {confirming && (
          <div className="mt-4 rounded-3xl bg-red-50 p-4 text-sm text-red-900">
            <p className="font-medium">¿Pedir la baja de tu cuenta?</p>
            <p className="mt-1 text-red-800">
              Becode borra tu cuenta y tus datos personales dentro de los 5 días hábiles. Las reuniones que hiciste para
              una institución quedan en la institución. No se puede deshacer.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                onClick={() => ask.mutate()}
                disabled={ask.isPending}
                className="min-h-11 rounded-full bg-red-600 px-4 font-medium text-white hover:bg-red-700 disabled:opacity-50"
              >
                {ask.isPending ? <Spinner /> : "Sí, pedir la baja"}
              </button>
              <button onClick={() => setConfirming(false)} className="min-h-11 rounded-full px-4 font-medium text-red-800">
                Cancelar
              </button>
            </div>
          </div>
        )}
        {deletion?.requested_at && (
          <p className="mt-4 rounded-3xl bg-ink-50 px-4 py-3 text-sm text-ink-600">
            Pediste la baja el {new Date(deletion.requested_at).toLocaleDateString("es-AR")}. Becode la procesa dentro de
            los 5 días hábiles y te avisa por mail.
          </p>
        )}
        {ask.isError && <ErrorText error={ask.error} fallback="No se pudo pedir" />}
      </Block>
    </div>
  );
}
