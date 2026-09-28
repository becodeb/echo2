import { pressScale } from "../anim";
import { CLICK } from "../timeline";

/**
 * pages/ActaPrint.tsx: la hoja del acta que abre "Imprimir" (estilos de
 * acta-print.css). Es otra página, sin barra lateral: ocupa toda la app. Se
 * muestra al 80 % (como el zoom del navegador) para que entre la hoja entera,
 * con las firmas y el pie "Acta aprobada".
 */
export const PRINT_SCALE = 0.8;
export const PRINT_TOP = 16;
const TOOLBAR_W = 800;
/** Coordenadas en la app de lo que toca el cursor. */
export const PRINT_VOLVER = { x: 640 - (TOOLBAR_W / 2) * PRINT_SCALE + 64 * PRINT_SCALE, y: PRINT_TOP + 20 * PRINT_SCALE };
/** Zona del pie y las firmas (para la cámara). */
export const PRINT_FOOT = { x: 640, y: 560 };

export function ActaPrint({ frame }: { frame: number }) {
  return (
    <div className="absolute inset-0 overflow-hidden" style={{ background: "#eceef2" }}>
      <div
        className="absolute left-1/2"
        style={{ width: TOOLBAR_W, top: PRINT_TOP, transform: `translateX(-50%) scale(${PRINT_SCALE})`, transformOrigin: "50% 0" }}
      >
        <div className="mb-4 flex items-center justify-between" style={{ height: 40 }}>
          <span
            style={{ fontSize: 14, color: "#4a5268", transform: `scale(${pressScale(frame, CLICK.volver)})`, transformOrigin: "left center" }}
          >
            Volver a la reunión
          </span>
          <span
            className="inline-flex items-center"
            style={{ height: 40, padding: "0 18px", borderRadius: 999, background: "#0c0e16", color: "#fafbfc", fontSize: 14, fontWeight: 500 }}
          >
            Imprimir
          </span>
        </div>
        <article
          style={{
            padding: "56px 64px 48px",
            background: "#ffffff",
            color: "#141824",
            fontFamily: 'Arial, Helvetica, "Liberation Sans", sans-serif',
            fontSize: 13.5,
            lineHeight: 1.6,
            boxShadow: "0 1px 2px rgba(16, 24, 40, 0.06), 0 12px 40px rgba(16, 24, 40, 0.08)",
          }}
        >
          <p style={{ margin: "0 0 8px", textAlign: "right", fontSize: 12, fontWeight: 700 }}>Acta N.º 14</p>
          <header style={{ minHeight: 48 }}>
            {["Colegio San Martín · Nivel Primario", "Av. Belgrano 1450 · Tel. 4555-0102"].map((line) => (
              <p key={line} style={{ margin: 0, fontSize: 12, lineHeight: 1.5, color: "#646e84" }}>
                {line}
              </p>
            ))}
          </header>
          <p style={{ margin: "18px 0 0", fontSize: 12.5, color: "#363d4f" }}>
            <strong>Colegio San Martín</strong>
          </p>
          <h1 style={{ margin: "28px 0 8px", textAlign: "center", fontSize: 16, fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase" }}>
            Acta de reunión
          </h1>
          <p style={{ margin: "0 0 24px", textAlign: "center", fontSize: 12, color: "#646e84" }}>
            Familia Romero · 28 sept · 24 min · Directora, Orientadora (DOE), Mamá de Pedro
          </p>
          <div className="text-[15px] leading-relaxed text-ink-800">
            <h2 className="mb-2 text-lg font-semibold">Motivo</h2>
            <p className="my-2">Seguimiento de convivencia: Pedro está más callado y no quiere venir al colegio.</p>
            <h2 className="mb-2 mt-5 text-lg font-semibold">Acuerdos</h2>
            <ul className="my-2 list-disc pl-5">
              <li className="my-0.5">Reunión con la psicopedagoga el viernes 2 de octubre.</li>
            </ul>
            <h2 className="mb-2 mt-5 text-lg font-semibold">Compromisos</h2>
            <ul className="my-2 list-disc pl-5">
              <li className="my-0.5">Directora: coordinar el horario con la psicopedagoga.</li>
              <li className="my-0.5">Orientadora (DOE): seguimiento con la familia.</li>
            </ul>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 40, marginTop: 64 }}>
            {["Directora", "Orientadora (DOE)", "Familia"].map((label) => (
              <span key={label} style={{ display: "block", paddingTop: 8, borderTop: "1px solid #141824", textAlign: "center", fontSize: 12, color: "#363d4f" }}>
                {label}
              </span>
            ))}
          </div>
          <p style={{ margin: "36px 0 0", fontSize: 11, color: "#8b94a7", textAlign: "right" }}>
            Acta aprobada · versión 1 · Generada con Echo
          </p>
        </article>
      </div>
    </div>
  );
}
