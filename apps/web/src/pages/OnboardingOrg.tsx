import { useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAuth } from "../state/auth";
import { Button, Input, Spinner } from "../components/ui";
import { EchoFace } from "../components/EchoFace";
import { GoogleButton } from "../components/GoogleButton";

interface JoinOptions {
  requires_google: boolean;
  organizations: { id: string; name: string }[];
}

/**
 * Bienvenida de quien todavía no está en ninguna organización.
 *
 * Si su email es de un colegio configurado (dominio o email exacto, ver
 * services/org_join.py), lo primero es elegir la sede; crear una
 * organización nueva o usar un código de invitación queda como alternativa.
 */
export default function OnboardingOrg() {
  const { user, logout } = useAuth();
  const [mode, setMode] = useState<"campus" | "create" | "join">("campus");

  const { data: options, isLoading } = useQuery({
    queryKey: ["join-options"],
    queryFn: () => api<JoinOptions>("/api/auth/join-options", { skipOrg: true }),
  });

  const hasCampus = (options?.organizations.length ?? 0) > 0;
  const effectiveMode = mode === "campus" && !hasCampus ? "create" : mode;

  return (
    <div className="flex min-h-dvh items-center justify-center bg-[#fafbfc] p-4">
      <div className="w-full max-w-md">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <span className="text-ink-900"><EchoFace mood="idle" size={44} /></span>
          <h1 className="text-2xl font-semibold tracking-tight text-ink-900">
            Hola, {user?.name.split(" ")[0]}
          </h1>
          <p className="text-sm text-ink-500">
            {hasCampus
              ? options!.requires_google
                ? "Tu email es de una institución que ya usa Echo."
                : "Tu email es de una institución que ya usa Echo. ¿De qué sede sos?"
              : "Echo organiza reuniones por organización. Creá la tuya o unite con una invitación."}
          </p>
        </div>

        {isLoading ? (
          <div className="flex justify-center py-10 text-ink-300"><Spinner className="h-6 w-6" /></div>
        ) : effectiveMode === "campus" && options ? (
          <CampusChoice options={options} />
        ) : (
          <CreateOrJoin mode={effectiveMode === "join" ? "join" : "create"} onMode={setMode} />
        )}

        {!isLoading && (
          <div className="mt-4 flex flex-col items-center gap-2 text-sm">
            {hasCampus && effectiveMode === "campus" && (
              <p className="text-center text-ink-400">
                ¿No es tu caso?{" "}
                <button onClick={() => setMode("join")} className="font-medium text-ink-600 hover:text-ink-900">
                  Tengo un código de invitación
                </button>{" "}
                ·{" "}
                <button onClick={() => setMode("create")} className="font-medium text-ink-600 hover:text-ink-900">
                  Crear otra organización
                </button>
              </p>
            )}
            {hasCampus && effectiveMode !== "campus" && (
              <button onClick={() => setMode("campus")} className="font-medium text-accent-600 hover:underline">
                Volver a elegir mi sede
              </button>
            )}
            <button onClick={() => logout()} className="text-ink-400 hover:text-ink-600">
              Cerrar sesión
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function CampusChoice({ options }: { options: JoinOptions }) {
  const [joining, setJoining] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (options.requires_google) {
    return (
      <div className="space-y-3 rounded-2xl border border-ink-100 bg-white p-6 shadow-sm">
        <p className="text-sm text-ink-700">
          Para entrar a <span className="font-medium">{options.organizations.map((org) => org.name).join(" o ")}</span>{" "}
          tenés que usar el botón de Google con tu cuenta institucional. Así Echo confirma que el email
          es tuyo; con contraseña no puede.
        </p>
        <GoogleButton label="Continuar con Google" />
      </div>
    );
  }

  const join = async (orgId: string) => {
    setJoining(orgId);
    setError(null);
    try {
      await api("/api/auth/join", {
        method: "POST",
        body: JSON.stringify({ organization_id: orgId }),
        skipOrg: true,
      });
      // Recarga completa: la sesión se vuelve a pedir y ya trae la sede.
      window.location.href = "/";
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo entrar");
      setJoining(null);
    }
  };

  return (
    <div className="space-y-2 rounded-2xl border border-ink-100 bg-white p-3 shadow-sm">
      {options.organizations.map((org) => (
        <button
          key={org.id}
          onClick={() => void join(org.id)}
          disabled={joining !== null}
          className="flex w-full items-center justify-between gap-3 rounded-xl border border-ink-100 px-4 py-3.5 text-left transition-colors hover:border-ink-300 hover:bg-ink-50 disabled:opacity-60"
        >
          <span className="font-medium text-ink-900">{org.name}</span>
          {joining === org.id ? (
            <Spinner className="text-ink-400" />
          ) : (
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden className="text-ink-400">
              <path d="m6 3 5 5-5 5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          )}
        </button>
      ))}
      {error && <p className="px-1 pt-1 text-sm text-red-600">{error}</p>}
      <p className="px-1 pt-1 text-xs text-ink-400">
        Entrás como miembro. Si necesitás otro permiso, lo cambia un administrador de tu sede.
      </p>
    </div>
  );
}

function CreateOrJoin({ mode, onMode }: { mode: "create" | "join"; onMode: (mode: "create" | "join") => void }) {
  const { createOrganization } = useAuth();
  const [name, setName] = useState("");
  const [inviteToken, setInviteToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "create") {
        await createOrganization(name);
      } else {
        await api("/api/auth/invites/accept", {
          method: "POST",
          body: JSON.stringify({ token: inviteToken.trim() }),
          skipOrg: true,
        });
      }
      window.location.href = "/";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="mb-4 flex rounded-lg bg-ink-100 p-1">
        {(["create", "join"] as const).map((option) => (
          <button
            key={option}
            onClick={() => onMode(option)}
            className={`flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
              mode === option ? "bg-white text-ink-900 shadow-sm" : "text-ink-500"
            }`}
          >
            {option === "create" ? "Crear organización" : "Tengo una invitación"}
          </button>
        ))}
      </div>

      <form onSubmit={submit} className="space-y-4 rounded-2xl border border-ink-100 bg-white p-6 shadow-sm">
        {mode === "create" ? (
          <Input
            label="Nombre de la organización"
            placeholder="Mi empresa"
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        ) : (
          <>
            <Input
              label="Código de invitación"
              placeholder="Pegá el código que te pasaron"
              required
              value={inviteToken}
              onChange={(event) => setInviteToken(event.target.value)}
            />
            <p className="text-xs text-ink-400">
              El código lo genera un administrador de la organización en Ajustes → Organización →
              Invitar, con tu email. Pedíselo y pegalo acá.
            </p>
          </>
        )}
        {error && <p className="text-sm text-red-600">{error}</p>}
        <Button type="submit" disabled={busy} className="w-full">
          {busy ? <Spinner /> : "Continuar"}
        </Button>
      </form>
    </>
  );
}
