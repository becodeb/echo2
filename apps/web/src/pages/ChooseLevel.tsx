import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { EchoFace } from "../components/EchoFace";
import { Button, Spinner } from "../components/ui";
import { LEVELS, type Level, type MyAccess } from "../state/access";
import { useAuth } from "../state/auth";

/**
 * Primera vez en la sede: ¿de qué nivel sos?
 *
 * Se puede marcar más de uno (ej. una psicopedagoga de primaria y
 * secundaria). Elegir no da acceso a las reuniones de los demás: se entra con
 * acceso limitado y el total lo da dirección.
 */
export default function ChooseLevel() {
  const { user, activeOrg, logout } = useAuth();
  const queryClient = useQueryClient();
  const [chosen, setChosen] = useState<Set<Level>>(new Set());

  const save = useMutation({
    mutationFn: () =>
      api<MyAccess>("/api/org/access/me", {
        method: "POST",
        body: JSON.stringify({ levels: LEVELS.map((l) => l.value).filter((value) => chosen.has(value)) }),
      }),
    onSuccess: (access) => queryClient.setQueryData(["my-access", activeOrg?.id], access),
  });

  const toggle = (level: Level) => {
    const next = new Set(chosen);
    if (next.has(level)) next.delete(level);
    else next.add(level);
    setChosen(next);
  };

  return (
    <div className="flex min-h-dvh items-center justify-center bg-[#fafbfc] p-4">
      <div className="w-full max-w-md">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <span className="text-ink-900"><EchoFace mood="idle" size={44} /></span>
          <h1 className="text-2xl font-semibold tracking-tight text-ink-900">
            Hola, {user?.name.split(" ")[0]}
          </h1>
          <p className="text-sm font-medium text-ink-700">{activeOrg?.name}</p>
          <p className="text-sm text-ink-500">¿De qué nivel sos? Podés marcar más de uno.</p>
        </div>

        <div className="space-y-2 rounded-2xl border border-ink-100 bg-white p-3 shadow-sm">
          {LEVELS.map((level) => {
            const active = chosen.has(level.value);
            return (
              <button
                key={level.value}
                type="button"
                onClick={() => toggle(level.value)}
                aria-pressed={active}
                className={`flex w-full items-center justify-between rounded-xl border px-4 py-3.5 text-left transition-colors ${
                  active ? "border-ink-900 bg-ink-900 text-white" : "border-ink-100 text-ink-900 hover:border-ink-300 hover:bg-ink-50"
                }`}
              >
                <span className="font-medium">{level.label}</span>
                <span
                  className={`flex h-5 w-5 items-center justify-center rounded-md border ${
                    active ? "border-white bg-white text-ink-900" : "border-ink-300"
                  }`}
                  aria-hidden
                >
                  {active && (
                    <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
                      <path d="m3.5 8.5 3 3 6-7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  )}
                </span>
              </button>
            );
          })}
          {save.isError && (
            <p className="px-1 text-sm text-red-600">
              {save.error instanceof Error ? save.error.message : "No se pudo guardar"}
            </p>
          )}
          <Button className="w-full" disabled={chosen.size === 0 || save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? <Spinner /> : "Continuar"}
          </Button>
          <p className="px-1 text-xs text-ink-400">
            Vas a ver tus reuniones y las que te compartan. Para ver todas las de tu nivel, pedíselo a
            dirección.
          </p>
        </div>

        <button onClick={() => logout()} className="mt-4 w-full text-center text-sm text-ink-400 hover:text-ink-600">
          Cerrar sesión
        </button>
      </div>
    </div>
  );
}
