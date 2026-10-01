import { useEffect } from "react";

/** El título de la pestaña ("Reuniones · Echo"). */
export function useTitle(title: string | null | undefined) {
  useEffect(() => {
    document.title = title ? `${title} · Echo` : "Echo · Actas de las reuniones del colegio";
  }, [title]);
}
