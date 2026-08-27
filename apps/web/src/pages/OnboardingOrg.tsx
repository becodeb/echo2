import { useState, type FormEvent } from "react";
import { useAuth } from "../state/auth";
import { Button, Input, Spinner } from "../components/ui";
import { EchoFace } from "../components/EchoFace";

export default function OnboardingOrg() {
  const { createOrganization, user, logout } = useAuth();
  const [name, setName] = useState("");
  const [inviteToken, setInviteToken] = useState("");
  const [mode, setMode] = useState<"create" | "join">("create");
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
        const { api } = await import("../api/client");
        await api("/api/auth/invites/accept", {
          method: "POST",
          body: JSON.stringify({ token: inviteToken.trim() }),
          skipOrg: true,
        });
        window.location.reload();
        return;
      }
      window.location.href = "/";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#fafbfc] p-4">
      <div className="w-full max-w-md">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <span className="text-ink-900"><EchoFace mood="idle" size={44} /></span>
          <h1 className="text-2xl font-semibold tracking-tight text-ink-900">
            Hola, {user?.name.split(" ")[0]}
          </h1>
          <p className="text-sm text-ink-500">
            Echo organiza reuniones por organización. Creá la tuya o unite con una invitación.
          </p>
        </div>

        <div className="mb-4 flex rounded-lg bg-ink-100 p-1">
          {(["create", "join"] as const).map((option) => (
            <button
              key={option}
              onClick={() => setMode(option)}
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
            <Input
              label="Código de invitación"
              placeholder="Pegá el token que te compartieron"
              required
              value={inviteToken}
              onChange={(event) => setInviteToken(event.target.value)}
            />
          )}
          {error && <p className="text-sm text-red-600">{error}</p>}
          <Button type="submit" disabled={busy} className="w-full">
            {busy ? <Spinner /> : "Continuar"}
          </Button>
        </form>
        <button onClick={() => logout()} className="mt-4 w-full text-center text-sm text-ink-400 hover:text-ink-600">
          Cerrar sesión
        </button>
      </div>
    </div>
  );
}
