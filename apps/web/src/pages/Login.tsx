import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../state/auth";
import { Button, Input, Spinner } from "../components/ui";
import { EchoFace } from "../components/EchoFace";
import { GoogleButton } from "../components/GoogleButton";

/** Motivos que puede devolver el callback de Google, en castellano y sin
 *  detalle técnico: la persona solo necesita saber qué hacer ahora. */
const OAUTH_ERRORS: Record<string, string> = {
  google: "No pudimos completar el ingreso con Google. Probá de nuevo.",
  google_state: "El ingreso con Google tardó demasiado. Probá de nuevo.",
  google_cancelado: "Cancelaste el ingreso con Google.",
  google_no_configurado: "El ingreso con Google no está disponible por ahora.",
  cuenta_deshabilitada: "Esa cuenta está deshabilitada.",
};

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const oauthError = OAUTH_ERRORS[params.get("error") ?? ""] ?? null;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al iniciar sesión");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#fafbfc] p-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-3">
          <span className="text-ink-900"><EchoFace mood="idle" size={44} /></span>
          <h1 className="text-2xl font-semibold tracking-tight text-ink-900">Echo</h1>
          <p className="text-sm text-ink-500">La reunión termina. Echo recuerda.</p>
        </div>
        <div className="rounded-2xl border border-ink-100 bg-white p-6 shadow-sm">
          {oauthError && (
            <p className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{oauthError}</p>
          )}
          <form onSubmit={submit} className="space-y-4">
            <Input
              label="Email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
            <Input
              label="Contraseña"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
            {error && <p className="text-sm text-red-600">{error}</p>}
            <Button type="submit" disabled={busy} className="w-full">
              {busy ? <Spinner /> : "Iniciar sesión"}
            </Button>
          </form>
          <GoogleButton label="Continuar con Google" />
        </div>
        <p className="mt-4 text-center text-sm text-ink-500">
          ¿No tenés cuenta?{" "}
          <Link to="/register" className="font-medium text-accent-600 hover:underline">
            Crear cuenta
          </Link>
        </p>
      </div>
    </div>
  );
}
