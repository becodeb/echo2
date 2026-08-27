import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../state/auth";
import { Button, Input, Spinner } from "../components/ui";
import { EchoFace } from "../components/EchoFace";

export default function Register() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (password.length < 8) {
      setError("La contraseña necesita al menos 8 caracteres");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await register(name, email, password);
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al crear la cuenta");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#fafbfc] p-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-3">
          <span className="text-ink-900"><EchoFace mood="done" size={44} /></span>
          <h1 className="text-2xl font-semibold tracking-tight text-ink-900">Crear cuenta</h1>
        </div>
        <form onSubmit={submit} className="space-y-4 rounded-2xl border border-ink-100 bg-white p-6 shadow-sm">
          <Input label="Nombre" required value={name} onChange={(event) => setName(event.target.value)} />
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
            autoComplete="new-password"
            required
            minLength={8}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          {error && <p className="text-sm text-red-600">{error}</p>}
          <Button type="submit" disabled={busy} className="w-full">
            {busy ? <Spinner /> : "Crear cuenta"}
          </Button>
        </form>
        <p className="mt-4 text-center text-sm text-ink-500">
          ¿Ya tenés cuenta?{" "}
          <Link to="/login" className="font-medium text-accent-600 hover:underline">
            Iniciar sesión
          </Link>
        </p>
      </div>
    </div>
  );
}
