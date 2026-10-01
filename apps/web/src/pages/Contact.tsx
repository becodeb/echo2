import { useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { Button, Input, Spinner } from "../components/ui";
import { LegalShell } from "./Legal";

/**
 * Contacto con Becode sin mostrar ningún mail (routers/contact.py): ventas
 * ("Contact sales" de Planes y la landing), ejercer derechos sobre los datos,
 * ayuda. `?tema=privacidad` llega desde Privacidad.
 */

const TOPICS = [
  { value: "ventas", label: "Planes e instituciones" },
  { value: "privacidad", label: "Mis datos (acceso, corrección o baja)" },
  { value: "soporte", label: "Ayuda con Echo" },
  { value: "otro", label: "Otro tema" },
] as const;

type Topic = (typeof TOPICS)[number]["value"];

export default function Contact() {
  const [params] = useSearchParams();
  const initial = TOPICS.find((topic) => topic.value === params.get("tema"))?.value ?? "ventas";
  const [topic, setTopic] = useState<Topic>(initial);
  const [form, setForm] = useState({ name: "", email: "", organization: "", message: "", website: "" });
  const [state, setState] = useState<"idle" | "sending" | "sent">("idle");
  const [error, setError] = useState<string | null>(null);

  const set = (key: keyof typeof form) => (event: { target: { value: string } }) =>
    setForm((current) => ({ ...current, [key]: event.target.value }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setState("sending");
    setError(null);
    try {
      await api("/api/contact", {
        method: "POST",
        skipOrg: true,
        body: JSON.stringify({ ...form, topic, organization: form.organization || null }),
      });
      setState("sent");
    } catch (err) {
      setState("idle");
      setError(err instanceof Error ? err.message : "No se pudo mandar. Probá de nuevo en un momento.");
    }
  };

  return (
    <LegalShell>
      <div className="animate-fade-up">
        <h1 className="text-3xl font-semibold tracking-tight text-ink-900 sm:text-4xl">Hablemos</h1>
        <p className="mt-3 text-[17px] leading-relaxed text-ink-600">
          Contanos qué necesitás y te respondemos por mail. Los pedidos sobre tus datos los respondemos dentro de los
          plazos de la Ley 25.326.
        </p>

        {state === "sent" ? (
          <div className="mt-8 rounded-3xl border border-emerald-100 bg-emerald-50 px-6 py-8 text-emerald-900">
            <p className="text-lg font-semibold">¡Listo, nos llegó!</p>
            <p className="mt-1 text-sm text-emerald-800">Te escribimos a {form.email} lo antes posible.</p>
          </div>
        ) : (
          <form onSubmit={submit} className="mt-8 space-y-5 rounded-3xl border border-ink-100 bg-white p-6 sm:p-8">
            <fieldset>
              <legend className="mb-2 text-sm font-medium text-ink-700">¿Sobre qué es?</legend>
              <div className="flex flex-wrap gap-2">
                {TOPICS.map((item) => (
                  <button
                    key={item.value}
                    type="button"
                    aria-pressed={topic === item.value}
                    onClick={() => setTopic(item.value)}
                    className={`min-h-11 rounded-full px-4 text-sm font-medium transition-colors ${
                      topic === item.value ? "bg-ink-900 text-white" : "bg-ink-100 text-ink-600 hover:bg-ink-200"
                    }`}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </fieldset>
            <div className="grid gap-4 sm:grid-cols-2">
              <Input label="Tu nombre" value={form.name} onChange={set("name")} required autoComplete="name" />
              <Input label="Tu email" type="email" value={form.email} onChange={set("email")} required autoComplete="email" />
            </div>
            {topic === "ventas" && (
              <Input label="Institución (opcional)" value={form.organization} onChange={set("organization")} />
            )}
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-ink-700">Mensaje</span>
              <textarea
                value={form.message}
                onChange={set("message")}
                required
                rows={5}
                maxLength={4000}
                className="w-full rounded-2xl border border-ink-200 bg-white px-3 py-2 text-sm text-ink-900 placeholder:text-ink-400 focus:border-accent-500 focus:outline-none focus:ring-2 focus:ring-accent-500/20"
                placeholder={
                  topic === "privacidad"
                    ? "Ej.: quiero saber qué datos tienen de mí / quiero que borren mi cuenta."
                    : topic === "ventas"
                      ? "Ej.: somos un colegio de 3 niveles y queremos probar Echo."
                      : ""
                }
              />
            </label>
            {/* Trampa para bots: oculto para las personas. */}
            <div aria-hidden className="absolute -left-[9999px] h-0 w-0 overflow-hidden">
              <input type="text" tabIndex={-1} autoComplete="off" value={form.website} onChange={set("website")} />
            </div>
            {error && <p className="text-sm text-red-600">{error}</p>}
            <Button type="submit" disabled={state === "sending"} className="min-h-11 w-full sm:w-auto">
              {state === "sending" ? <Spinner /> : "Enviar"}
            </Button>
          </form>
        )}
      </div>
    </LegalShell>
  );
}

