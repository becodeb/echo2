import type { ReactNode } from "react";
import { Spinner } from "../../components/ui";

/**
 * Un bloque de una sección de Ajustes: sin tarjeta (la ventana ya es una),
 * separado del anterior por una línea. `id` es el data-setting-id al que
 * salta el buscador.
 */
export function Block({
  id,
  title,
  hint,
  action,
  children,
}: {
  id?: string;
  title?: ReactNode;
  hint?: ReactNode;
  action?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <section
      data-setting-id={id}
      // -mx/px: el resaltado del buscador tiene aire a los costados.
      className="-mx-3 scroll-mt-4 rounded-2xl border-t border-ink-100 px-3 py-6 first:border-t-0 first:pt-1"
    >
      {(title || action) && (
        <div className="mb-1 flex items-center justify-between gap-3">
          {title && <h3 className="text-[15px] font-semibold text-ink-900">{title}</h3>}
          {action}
        </div>
      )}
      {hint && <p className="mb-4 text-sm leading-relaxed text-ink-500">{hint}</p>}
      {children}
    </section>
  );
}

export function Loading() {
  return (
    <div className="flex justify-center py-10 text-ink-300">
      <Spinner className="h-5 w-5" />
    </div>
  );
}

export function ErrorText({ error, fallback }: { error: unknown; fallback: string }) {
  return <p className="mt-2 text-sm text-red-600">{error instanceof Error ? error.message : fallback}</p>;
}
