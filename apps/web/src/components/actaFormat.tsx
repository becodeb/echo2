import type { CSSProperties, ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { LetterheadOut } from "../api/types";
import "./acta-format.css";

/** La fuente que el colegio eligió para sus actas (Ajustes → Membrete). */
export const ACTA_FONT_CSS: Record<string, string> = {
  arial: 'Arial, Helvetica, "Liberation Sans", sans-serif',
  calibri: 'Calibri, Carlito, "Segoe UI", Arial, sans-serif',
  times: '"Times New Roman", Times, "Liberation Serif", serif',
  trebuchet: '"Trebuchet MS", "Segoe UI", Arial, sans-serif',
};

/**
 * Cuánto crece la letra del acta respecto de la de siempre. Son las mismas
 * proporciones que Word (11 → 13 → 15 pt): los 12 pt del formulario de
 * entrevista quedan en 14 y 16.
 */
export const ACTA_SCALE = { normal: 1, grande: 1.17, muy_grande: 1.33 } as const;
/** Sencillo apreta los renglones; 1,5 es como se vio siempre. */
export const ACTA_LINE_RATIO = { simple: 0.8, "1.5": 1 } as const;
/** Angostos: 13 mm en vez de 18 mm, lo mismo que en Word y PDF. */
export const ACTA_MARGIN_RATIO = { normal: 1, angosto: 0.72 } as const;

type ActaFormat = Pick<LetterheadOut, "font" | "font_size" | "line_spacing" | "margins">;

export function actaScale(format: Partial<ActaFormat>) {
  return {
    scale: ACTA_SCALE[format.font_size ?? "normal"] ?? 1,
    line: ACTA_LINE_RATIO[format.line_spacing ?? "1.5"] ?? 1,
    margin: ACTA_MARGIN_RATIO[format.margins ?? "normal"] ?? 1,
  };
}

/**
 * Las variables CSS con que la hoja (acta-print.css), los formularios
 * (interview-sheet.css) y la vista en la reunión arman la letra, el
 * interlineado y los márgenes del acta.
 */
export function actaFormatVars(format: Partial<ActaFormat>): CSSProperties {
  const { scale, line, margin } = actaScale(format);
  return {
    "--acta-font": ACTA_FONT_CSS[format.font ?? "arial"] ?? ACTA_FONT_CSS.arial,
    "--acta-scale": scale,
    "--acta-lh": line,
    "--acta-margin": margin,
  } as CSSProperties;
}

/** El acta en la reunión, con la letra e interlineado que eligió la sede. */
export function ActaFormatted({ children }: { children: ReactNode }) {
  const { data: letterhead } = useQuery({
    queryKey: ["letterhead"],
    queryFn: () => api<LetterheadOut>("/api/org/letterhead"),
  });
  return (
    <div className="acta-formato" style={letterhead ? actaFormatVars(letterhead) : undefined}>
      {children}
    </div>
  );
}
