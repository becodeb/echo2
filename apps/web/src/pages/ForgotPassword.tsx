import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { EchoFace } from "../components/EchoFace";
import { Button, Input, Spinner } from "../components/ui";
import { useTitle } from "../lib/useTitle";

/**
 * "Olvidé mi contraseña" (/olvide) y la contraseña nueva (/restablecer?token=…).
 * Son públicas: el link llega por mail y se puede abrir con o sin sesión.
 */
export default function ForgotPassword() {
  const [params] = useSearchParams();
  const token = params.get("token");
  useTitle(token ? "Contraseña nueva" : "Olvidé mi contraseña");
  return (
    <div className="flex min-h-screen items-center justify-center bg-[#fafbfc] p-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-3">
          <span className="text-ink-900">
            <EchoFace mood="idle" size={44} />
          </span>
          <h1 className="text-2xl font-semibold tracking-tight text-ink-900">
            {token ? "Elegí una contraseña nueva" : "¿Olvidaste tu contraseña?"}
          </h1>
        </div>
        <div className="rounded-3xl border border-ink-100 bg-white p-6 shadow-sm">
          {token ? <NewPassword token={token} /> : <AskForLink />}
        </div>
        <p className="mt-4 text-center text-sm text-ink-500">
          <Link to="/login" className="font-medium text-accent-600 hover:underline">
            Volver a Ingresar
          </Link>
        </p>
      </div>
    </div>
  );
}

function AskForLink() {
  const [email, setEmail] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "sent">("idle");
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setState("sending");
    setError(null);
    try {
      await api("/api/auth/password/forgot", { method: "POST", skipOrg: true, body: JSON.stringify({ email }) });
      setState("sent");
    } catch (err) {
      setState("idle");
      setError(err instanceof Error ? err.message : "No se pudo pedir. Probá de nuevo.");
    }
  };

  if (state === "sent") {
    return (
      <p className="text-sm leading-relaxed text-ink-600">
        Si hay una cuenta con <strong className="text-ink-900">{email}</strong>, te llega un link para elegir una
        contraseña nueva. Vence en una hora. Si entrás con Google, también podés usar «Continuar con Google».
      </p>
    );
  }
  return (
    <form onSubmit={submit} className="space-y-4">
      <p className="text-sm text-ink-500">Escribí tu email y te mandamos un link para elegir una contraseña nueva.</p>
      <Input label="Email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
      {error && <p className="text-sm text-red-600">{error}</p>}
      <Button type="submit" disabled={state === "sending"} className="w-full">
        {state === "sending" ? <Spinner /> : "Mandame el link"}
      </Button>
    </form>
  );
}

function NewPassword({ token }: { token: string }) {
  const [password, setPassword] = useState("");
  const [state, setState] = useState<"idle" | "saving" | "done">("idle");
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setState("saving");
    setError(null);
    try {
      await api("/api/auth/password/reset", { method: "POST", skipOrg: true, body: JSON.stringify({ token, password }) });
      setState("done");
    } catch (err) {
      setState("idle");
      setError(err instanceof Error ? err.message : "No se pudo guardar.");
    }
  };

  if (state === "done") {
    return (
      <div className="space-y-4 text-sm text-ink-600">
        <p>¡Listo! Ya podés entrar con tu contraseña nueva. Las otras sesiones abiertas se cerraron.</p>
        <Link
          to="/login"
          className="inline-flex min-h-11 w-full items-center justify-center rounded-full bg-ink-900 font-semibold text-white"
        >
          Ingresar
        </Link>
      </div>
    );
  }
  return (
    <form onSubmit={submit} className="space-y-4">
      <Input
        label="Contraseña nueva (8 caracteres o más)"
        type="password"
        autoComplete="new-password"
        minLength={8}
        required
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      {error && (
        <p className="text-sm text-red-600">
          {error}{" "}
          <Link to="/olvide" className="font-medium underline">
            Pedir otro link
          </Link>
        </p>
      )}
      <Button type="submit" disabled={state === "saving"} className="w-full">
        {state === "saving" ? <Spinner /> : "Guardar"}
      </Button>
    </form>
  );
}
