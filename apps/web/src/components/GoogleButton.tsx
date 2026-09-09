import { useEffect, useState } from "react";

/**
 * Botón de Google para el login y el alta de cuenta.
 *
 * Se muestra solo si el servidor tiene configurado el cliente de OAuth: si no
 * hay credenciales, /api/auth/google/status devuelve enabled:false y el botón
 * no se renderiza, así nadie se topa con un flujo que no va a funcionar.
 *
 * No es un fetch con el cliente de la app a propósito: corre antes de que
 * exista sesión y no necesita token ni organización activa.
 */

function GoogleLogo() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62Z"
      />
      <path
        fill="#34A853"
        d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18Z"
      />
      <path
        fill="#FBBC05"
        d="M3.97 10.72a5.41 5.41 0 0 1 0-3.44V4.95H.96a9 9 0 0 0 0 8.1l3.01-2.33Z"
      />
      <path
        fill="#EA4335"
        d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58C13.46.89 11.43 0 9 0A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58Z"
      />
    </svg>
  );
}

export function GoogleButton({ label }: { label: string }) {
  const [enabled, setEnabled] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/auth/google/status")
      .then((response) => (response.ok ? response.json() : { enabled: false }))
      .then((data) => {
        if (!cancelled) setEnabled(Boolean(data?.enabled));
      })
      .catch(() => {
        /* sin Google configurado: el botón no aparece */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!enabled) return null;

  return (
    <div className="mt-5 space-y-4">
      <div className="flex items-center gap-3" aria-hidden="true">
        <span className="h-px flex-1 bg-ink-100" />
        <span className="text-xs font-medium uppercase tracking-wide text-ink-400">o</span>
        <span className="h-px flex-1 bg-ink-100" />
      </div>
      <a
        href="/api/auth/google/start"
        className="inline-flex w-full items-center justify-center gap-2.5 rounded-lg border border-ink-200 bg-white px-3.5 py-2 text-sm font-medium text-ink-800 transition-colors hover:bg-ink-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500"
      >
        <GoogleLogo />
        {label}
      </a>
    </div>
  );
}
