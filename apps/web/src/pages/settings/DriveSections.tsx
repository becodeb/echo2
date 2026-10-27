import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api } from "../../api/client";
import type { DriveStatusOut, MyDriveOut } from "../../api/types";
import { PaidOnly, usePaid } from "../../components/billing";
import { Button, Spinner } from "../../components/ui";
import { Block, ErrorText, Loading } from "./parts";

const DRIVE_ERRORS: Record<string, string> = {
  cancelado: "Cancelaste la conexión con Google Drive.",
  estado: "La conexión tardó demasiado. Probá de nuevo.",
  permisos: "Necesitás ser administrador de la organización para conectar Drive.",
  google: "Google rechazó la conexión. Probá de nuevo en un momento.",
  sin_refresh:
    "Google no devolvió un permiso duradero. Quitá el acceso de Echo en tu cuenta de Google y volvé a conectar.",
};

/** Lo que dejó la vuelta de Google en la URL: ?connected=1 o ?error=… */
function OAuthResult({ connected }: { connected: boolean | undefined }) {
  const [params] = useSearchParams();
  const oauthError = DRIVE_ERRORS[params.get("error") ?? ""] ?? null;
  return (
    <>
      {oauthError && <p className="mb-4 rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700">{oauthError}</p>}
      {params.get("connected") === "1" && connected && (
        <p className="mb-4 rounded-xl bg-emerald-50 px-3 py-2 text-sm text-emerald-700">Drive conectado.</p>
      )}
    </>
  );
}

const NO_GOOGLE =
  "El servidor no tiene credenciales de Google configuradas, así que esta integración no está disponible.";

export function DriveSection() {
  const paid = usePaid();
  const queryClient = useQueryClient();
  const [, setParams] = useSearchParams();

  const { data: drive, isLoading } = useQuery({
    queryKey: ["drive-status"],
    queryFn: () => api<DriveStatusOut>("/api/org/drive/status"),
  });

  const connect = useMutation({
    mutationFn: () => api<{ url: string }>("/api/org/drive/connect-url", { method: "POST" }),
    onSuccess: (data) => {
      window.location.href = data.url;
    },
  });

  const disconnect = useMutation({
    mutationFn: () => api("/api/org/drive", { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["drive-status"] }),
  });

  if (isLoading) return <Loading />;

  return (
    <div>
      <Block
        id="drive-connection"
        title="Conexión"
        hint="Una carpeta por familia y, adentro, una por reunión con la fecha y el motivo. Las actas se suben apenas se generan y se reemplazan en cada versión."
      >
        <OAuthResult connected={drive?.connected} />
        {drive?.last_error && (
          <p className="mb-4 rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-800">
            Última subida fallida: {drive.last_error}
          </p>
        )}

        {!drive?.enabled ? (
          <p className="text-sm text-ink-500">{NO_GOOGLE}</p>
        ) : drive.connected ? (
          <div className="space-y-3">
            <p className="text-sm text-ink-700">
              Conectada con <span className="font-medium">{drive.connected_email}</span>.
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="soft"
                onClick={() => {
                  setParams({}, { replace: true });
                  disconnect.mutate();
                }}
                disabled={disconnect.isPending}
              >
                {disconnect.isPending ? <Spinner /> : "Desconectar"}
              </Button>
              <span className="text-xs text-ink-400">
                Desconectar borra el permiso, no los archivos: lo que ya está en Drive queda.
              </span>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            {paid === false ? (
              <PaidOnly what="Guardar en el Drive de la sede" />
            ) : (
              <Button onClick={() => connect.mutate()} disabled={connect.isPending}>
                {connect.isPending ? <Spinner /> : "Conectar Google Drive"}
              </Button>
            )}
            {connect.isError && <ErrorText error={connect.error} fallback="No se pudo iniciar" />}
            <p className="text-xs text-ink-400">
              Echo pide el permiso mínimo de Drive: solo puede ver y tocar lo que él mismo crea. No accede al resto
              de tus archivos.
            </p>
          </div>
        )}
      </Block>

      {drive?.connected && drive.root_folder_url && (
        <Block
          id="drive-folder"
          title="Carpeta madre"
          hint="Movela adentro de la carpeta que compartís con el equipo (o compartila directamente) y todos ven lo que Echo va guardando; el acceso de Echo no depende de dónde esté. Las reuniones internas no van acá."
        >
          <a
            href={drive.root_folder_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm font-medium text-accent-600 hover:underline"
          >
            Abrir en Drive ↗
          </a>
        </Block>
      )}
    </div>
  );
}

/**
 * Drive personal: adonde van las grabaciones que hace cada persona. Separado
 * del de la sede (donde van las actas): la grabación es de quien grabó.
 */
export function MyDriveSection() {
  const paid = usePaid();
  const queryClient = useQueryClient();
  const [, setParams] = useSearchParams();

  const { data: drive, isLoading } = useQuery({
    queryKey: ["my-drive"],
    queryFn: () => api<MyDriveOut>("/api/me/drive", { skipOrg: true }),
  });
  const connect = useMutation({
    mutationFn: () => api<{ url: string }>("/api/me/drive/connect-url", { method: "POST", skipOrg: true }),
    onSuccess: (data) => {
      window.location.href = data.url;
    },
  });
  const disconnect = useMutation({
    mutationFn: () => api("/api/me/drive", { method: "DELETE", skipOrg: true }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["my-drive"] }),
  });

  if (isLoading) return <Loading />;

  return (
    <Block
      id="my-drive-connection"
      hint="Cuando grabás una reunión, al terminar Echo sube el audio a la carpeta «Echo — Grabaciones» de tu Drive y lo borra de sus servidores. Sin Drive conectado, el audio queda para descargar 48 horas y después se borra."
    >
      <OAuthResult connected={drive?.connected} />
      {drive?.last_error && (
        <p className="mb-4 rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-800">
          Última subida fallida: {drive.last_error}
        </p>
      )}

      {!drive?.enabled ? (
        <p className="text-sm text-ink-500">{NO_GOOGLE}</p>
      ) : drive.connected ? (
        <div className="space-y-3">
          <p className="text-sm text-ink-700">
            Conectado con <span className="font-medium">{drive.connected_email}</span>.
            {drive.folder_url && (
              <>
                {" "}
                <a
                  href={drive.folder_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-medium text-accent-600 hover:underline"
                >
                  Abrir la carpeta de grabaciones ↗
                </a>
              </>
            )}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="soft"
              onClick={() => {
                setParams({}, { replace: true });
                disconnect.mutate();
              }}
              disabled={disconnect.isPending}
            >
              {disconnect.isPending ? <Spinner /> : "Desconectar"}
            </Button>
            <span className="text-xs text-ink-400">Tus grabaciones que ya están en Drive quedan ahí.</span>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          {paid === false ? (
            <PaidOnly what="Guardar en Google Drive" />
          ) : (
            <Button onClick={() => connect.mutate()} disabled={connect.isPending}>
              {connect.isPending ? <Spinner /> : "Conectar mi Google Drive"}
            </Button>
          )}
          {connect.isError && <ErrorText error={connect.error} fallback="No se pudo iniciar" />}
          <p className="text-xs text-ink-400">
            Permiso mínimo: Echo solo ve y toca los archivos que él mismo crea en tu Drive.
          </p>
        </div>
      )}
    </Block>
  );
}
