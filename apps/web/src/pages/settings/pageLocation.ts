import { useLocation, type Location, type NavigateFunction } from "react-router-dom";

/**
 * Ajustes es una ventana encima de la página en la que estabas: /settings/...
 * no reemplaza lo de atrás. Acá se recuerda la última página que no era
 * Ajustes, para seguir mostrándola debajo y volver a ella al cerrar. Si se
 * entró directo (la vuelta de Google Drive, un link pegado), atrás va el Inicio.
 */

let lastPage: Location | null = null;
// La posición de esa página en el historial (la guarda BrowserRouter en history.state).
let lastPageIdx: number | null = null;

const HOME: Location = { pathname: "/", search: "", hash: "", state: null, key: "settings-home" };

export function isSettingsPath(pathname: string): boolean {
  return pathname === "/settings" || pathname.startsWith("/settings/");
}

function historyIdx(): number | null {
  const idx = (window.history.state as { idx?: unknown } | null)?.idx;
  return typeof idx === "number" ? idx : null;
}

/** La página que va debajo, y si Ajustes está abierto. */
export function usePageLocation(): { page: Location; settingsOpen: boolean } {
  const location = useLocation();
  if (!isSettingsPath(location.pathname)) {
    if (lastPage?.key !== location.key) {
      lastPage = location;
      lastPageIdx = historyIdx();
    }
    return { page: location, settingsOpen: false };
  }
  return { page: lastPage ?? HOME, settingsOpen: true };
}

/** Cierra Ajustes: vuelve atrás hasta la página de debajo, o al Inicio. */
export function closeSettings(navigate: NavigateFunction) {
  const idx = historyIdx();
  if (lastPage && idx != null && lastPageIdx != null && idx > lastPageIdx) {
    navigate(lastPageIdx - idx);
  } else if (lastPage) {
    navigate(`${lastPage.pathname}${lastPage.search}${lastPage.hash}`, { replace: true, state: lastPage.state });
  } else {
    navigate("/", { replace: true });
  }
}
