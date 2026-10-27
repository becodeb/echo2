import type { ReactNode } from "react";

/**
 * Íconos de la navegación, redondeados como los de ElevenLabs: trazo fino,
 * puntas y uniones redondas, y formas construidas con círculos y esquinas
 * suaves en vez de ángulos.
 */

function Svg({ children, size = 18 }: { children: ReactNode; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      {children}
    </svg>
  );
}

export type IconName =
  | "home"
  | "meetings"
  | "internal"
  | "tasks"
  | "projects"
  | "people"
  | "families"
  | "reports"
  | "ask"
  | "admin"
  | "usage"
  | "settings"
  | "gear"
  | "mic"
  | "cloud"
  | "shield"
  | "building"
  | "layers"
  | "hash"
  | "letterhead"
  | "book"
  | "device"
  | "chevron-left"
  | "close"
  | "search"
  | "bell"
  | "plans"
  | "logout"
  | "doc"
  | "check"
  | "comment"
  | "sparkle"
  | "megaphone";

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  switch (name) {
    case "home":
      // Como el de ElevenLabs: una casita de esquinas muy redondeadas, techo
      // suave y la puerta como una línea abajo (cuadrícula de 18, trazo 1,5).
      return (
        <svg width={size} height={size} viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M5.8 12.2h6.4" />
          <path d="M2.8 7.8c0-.9.4-1.7 1.1-2.3l3.6-2.9a2.4 2.4 0 0 1 3 0l3.6 2.9c.7.6 1.1 1.4 1.1 2.3v3.6c0 2.1-1.7 3.8-3.8 3.8H6.6c-2.1 0-3.8-1.7-3.8-3.8V7.8z" />
        </svg>
      );
    case "meetings":
      return (
        <Svg size={size}>
          <path d="M20 11.5a7.5 7.5 0 0 1-11 6.6L4.5 19.5l1.4-4A7.5 7.5 0 1 1 20 11.5z" />
          <circle cx="9" cy="11.5" r="0.6" fill="currentColor" />
          <circle cx="12.5" cy="11.5" r="0.6" fill="currentColor" />
          <circle cx="16" cy="11.5" r="0.6" fill="currentColor" />
        </Svg>
      );
    case "internal":
      // Dos globos de charla: la reunión entre el equipo (Reuniones es uno solo).
      return (
        <Svg size={size}>
          <path d="M14.5 6.2A6 6 0 0 0 3.5 9.5a5.9 5.9 0 0 0 .8 3L3.5 15l2.6-.8" />
          <path d="M20.5 14a5.5 5.5 0 0 1-.7 2.7l.7 2.8-2.8-.8A5.5 5.5 0 1 1 20.5 14z" />
        </Svg>
      );
    case "tasks":
      return (
        <Svg size={size}>
          <circle cx="6" cy="7" r="1.6" />
          <circle cx="6" cy="12" r="1.6" />
          <circle cx="6" cy="17" r="1.6" />
          <path d="M10.5 7H19M10.5 12H19M10.5 17H16" />
        </Svg>
      );
    case "projects":
      return (
        <Svg size={size}>
          <path d="M3.5 8A2 2 0 0 1 5.5 6h3.6a2 2 0 0 1 1.4.6l1 1h7a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2V8z" />
        </Svg>
      );
    case "people":
      return (
        <Svg size={size}>
          <circle cx="12" cy="8.5" r="3.5" />
          <path d="M5 19.5c.9-3.2 3.7-5 7-5s6.1 1.8 7 5" />
        </Svg>
      );
    case "families":
      return (
        <Svg size={size}>
          <circle cx="8.5" cy="8.5" r="2.8" />
          <circle cx="16" cy="9.5" r="2.3" />
          <path d="M3.5 19c.6-2.8 2.6-4.4 5-4.4s4.4 1.6 5 4.4" />
          <path d="M14.5 14.8c2.6-.5 5 .9 6 4.2" />
        </Svg>
      );
    case "reports":
      return (
        <Svg size={size}>
          <path d="M5 12v3M9 8v11M13 5v14M17 10v6M21 12v2" />
        </Svg>
      );
    case "ask":
      return (
        <Svg size={size}>
          <circle cx="12" cy="12" r="8.5" />
          <path d="M12 7.8 13 11l3.2 1-3.2 1-1 3.2-1-3.2-3.2-1 3.2-1z" />
        </Svg>
      );
    case "admin":
      return (
        <Svg size={size}>
          <circle cx="12" cy="12" r="8.5" />
          <circle cx="12" cy="10" r="2.5" />
          <path d="M7.5 17.5c1-1.8 2.6-2.8 4.5-2.8s3.5 1 4.5 2.8" />
        </Svg>
      );
    case "usage":
      return (
        <Svg size={size}>
          <path d="M4.5 15.5a7.5 7.5 0 1 1 15 0" />
          <path d="m12 15.5 3.5-4" />
          <circle cx="12" cy="15.5" r="1.2" />
        </Svg>
      );
    case "settings":
      return (
        <Svg size={size}>
          <circle cx="12" cy="12" r="3" />
          <path d="M12 3.5v2M12 18.5v2M3.5 12h2M18.5 12h2M6 6l1.4 1.4M16.6 16.6 18 18M6 18l1.4-1.4M16.6 7.4 18 6" />
        </Svg>
      );
    case "gear":
      // Ruedita con dientes redondeados: abre los ajustes y gira al tocarla.
      return (
        <Svg size={size}>
          <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
          <circle cx="12" cy="12" r="3" />
        </Svg>
      );
    case "mic":
      return (
        <Svg size={size}>
          <rect x="9" y="3.5" width="6" height="11" rx="3" />
          <path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v2.5" />
        </Svg>
      );
    case "cloud":
      return (
        <Svg size={size}>
          <path d="M7.5 18.5a4 4 0 0 1-.6-7.95 5.5 5.5 0 0 1 10.6 1.45 3.25 3.25 0 0 1-.5 6.5h-9.5z" />
        </Svg>
      );
    case "shield":
      return (
        <Svg size={size}>
          <path d="M12 3.5 5.5 6v5.5c0 4 2.8 7.3 6.5 9 3.7-1.7 6.5-5 6.5-9V6L12 3.5z" />
          <path d="m9.3 12.2 1.9 1.9 3.6-3.8" />
        </Svg>
      );
    case "building":
      return (
        <Svg size={size}>
          <path d="M4.5 20.5h15M6 20.5V9.5l6-4.5 6 4.5v11" />
          <path d="M10 20.5v-4a2 2 0 0 1 4 0v4M10 11.5h.01M14 11.5h.01" />
        </Svg>
      );
    case "layers":
      return (
        <Svg size={size}>
          <path d="m12 4 8 4-8 4-8-4 8-4z" />
          <path d="m4 12 8 4 8-4M4 16l8 4 8-4" />
        </Svg>
      );
    case "hash":
      return (
        <Svg size={size}>
          <path d="M9.5 4.5 8 19.5M16 4.5l-1.5 15M5 9h14.5M4.5 15H19" />
        </Svg>
      );
    case "letterhead":
      // Una hoja con la franja del encabezado y el logo arriba.
      return (
        <Svg size={size}>
          <rect x="5" y="3.5" width="14" height="17" rx="2" />
          <circle cx="9" cy="8" r="1.4" />
          <path d="M12.5 7.3h3.5M12.5 9h2.5M8 13h8M8 16.5h5" />
        </Svg>
      );
    case "book":
      return (
        <Svg size={size}>
          <path d="M5 5.5A2 2 0 0 1 7 3.5h11.5v14H7a2 2 0 0 0-2 2v-14z" />
          <path d="M5 19.5a2 2 0 0 0 2 1h11.5v-3M9 8h5.5" />
        </Svg>
      );
    case "device":
      return (
        <Svg size={size}>
          <rect x="4.5" y="6" width="15" height="12" rx="3" />
          <circle cx="12" cy="12" r="2.2" />
          <path d="M8 3.5h8" />
        </Svg>
      );
    case "chevron-left":
      return (
        <Svg size={size}>
          <path d="m14.5 6-6 6 6 6" />
        </Svg>
      );
    case "close":
      return (
        <Svg size={size}>
          <path d="m6.5 6.5 11 11M17.5 6.5l-11 11" />
        </Svg>
      );
    case "search":
      return (
        <Svg size={size}>
          <circle cx="11" cy="11" r="6.5" />
          <path d="m20 20-4.2-4.2" />
        </Svg>
      );
    case "bell":
      return (
        <Svg size={size}>
          <path d="M6.5 16.5V11a5.5 5.5 0 0 1 11 0v5.5l1.5 1.5H5l1.5-1.5z" />
          <path d="M10.2 20.5a2 2 0 0 0 3.6 0" />
        </Svg>
      );
    case "plans":
      return (
        <Svg size={size}>
          <circle cx="7" cy="12" r="2.2" />
          <circle cx="12" cy="12" r="2.2" />
          <circle cx="17" cy="12" r="2.2" fill="currentColor" />
        </Svg>
      );
    case "logout":
      return (
        <Svg size={size}>
          <path d="M14 4.5h3.5a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H14" />
          <path d="M10 8.5 6.5 12l3.5 3.5M6.5 12H15" />
        </Svg>
      );
    case "doc":
      return (
        <Svg size={size}>
          <path d="M7 3.5h6.5L18 8v11a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 6 19V5a1.5 1.5 0 0 1 1-1.5z" />
          <path d="M13 3.5V8h5M9 12.5h6M9 16h4" />
        </Svg>
      );
    case "check":
      return (
        <Svg size={size}>
          <circle cx="12" cy="12" r="8.5" />
          <path d="m8.5 12.2 2.4 2.4 4.6-4.8" />
        </Svg>
      );
    case "comment":
      return (
        <Svg size={size}>
          <path d="M6 5h12a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-6l-4 3v-3H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z" />
        </Svg>
      );
    case "sparkle":
      return (
        <Svg size={size}>
          <path d="M12 4 13.8 10.2 20 12l-6.2 1.8L12 20l-1.8-6.2L4 12l6.2-1.8z" />
        </Svg>
      );
    case "megaphone":
      return (
        <Svg size={size}>
          <path d="M4.5 10v4a1.5 1.5 0 0 0 1.5 1.5h2l7 4V4.5l-7 4H6A1.5 1.5 0 0 0 4.5 10z" />
          <path d="M18.5 9.5a3.5 3.5 0 0 1 0 5" />
        </Svg>
      );
  }
}
