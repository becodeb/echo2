import type { InterviewFields, LetterheadOut } from "../api/types";
import "./interview-sheet.css";

const MESES = [
  "enero", "febrero", "marzo", "abril", "mayo", "junio",
  "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
];

/** Renglones vacíos mínimos: la hoja llega al pie aunque el acta sea corta. */
const MIN_RULED_LINES = 16;

/**
 * El formulario "Acta de entrevista" del colegio, completo. Replica el papel:
 * membrete gris, logo centrado, campos punteados, casilleros Familia/Colegio,
 * el párrafo fijo y el desarrollo sobre renglones. Es lo que se imprime.
 */
export function InterviewSheet({ fields, letterhead }: { fields: InterviewFields; letterhead: LetterheadOut }) {
  const [year, month, day] = fields.fecha.split("-").map(Number);
  const place = letterhead.interview_place || `la institución ${letterhead.institution}`;
  const paragraphs = fields.desarrollo.split(/\n\s*\n|\n/).map((text) => text.trim()).filter(Boolean);

  return (
    <article className="entrevista-hoja">
      <header className="ent-membrete">
        {letterhead.lines.map((line, index) => (
          <p key={index}>{line}</p>
        ))}
      </header>
      {letterhead.logo_data_url && (
        <img src={letterhead.logo_data_url} alt={letterhead.institution} className="ent-logo" />
      )}
      <h1 className="ent-titulo">{letterhead.title || "ACTA DE ENTREVISTA"}</h1>

      <p className="ent-fila">
        <b>Nombre del alumno:</b>
        <Fill className="ent-grow">{fields.alumno}</Fill>
        <b className="ent-curso">Curso:</b>
        <Fill className="ent-corto">{fields.curso}</Fill>
      </p>

      <p className="ent-fila ent-solicitada">
        <b>Solicitada por:</b>
      </p>
      <p className="ent-checks">
        <Check checked={fields.solicitada_por === "familia"} label="Familia" />
        <Check checked={fields.solicitada_por === "colegio"} label="Colegio" />
      </p>

      <p className="ent-fila ent-motivo">
        <b>Motivo general :</b>
        <Fill className="ent-grow">{fields.motivo}</Fill>
      </p>

      <p className="ent-parrafo">
        A los <Fill>{day ? String(day) : ""}</Fill> días del mes de <Fill>{month ? MESES[month - 1] : ""}</Fill> de{" "}
        {year || "……"} en las instalaciones de {place}, se reúnen <Fill>{fields.reunen}</Fill>
      </p>

      <div className="ent-renglones" style={{ minHeight: `${MIN_RULED_LINES * 20}pt` }}>
        <p>con {fields.con}{fields.con && !/[.:]$/.test(fields.con) ? "." : ""}</p>
        {paragraphs.map((text, index) => (
          <p key={index}>{text}</p>
        ))}
      </div>

      {letterhead.signatures.length > 0 && (
        <footer className="ent-firmas">
          {letterhead.signatures.map((label, index) => (
            <span key={index}>{label}</span>
          ))}
        </footer>
      )}
    </article>
  );
}

function Fill({ children, className = "" }: { children: string; className?: string }) {
  // Vacío se ve como en el papel: una línea de puntos para completar a mano.
  return <span className={`ent-fill ${children ? "" : "ent-vacio"} ${className}`}>{children || " "}</span>;
}

function Check({ checked, label }: { checked: boolean; label: string }) {
  return (
    <span className="ent-check" role="img" aria-label={`${label}${checked ? " (marcado)" : ""}`}>
      <span className="ent-box">{checked ? "X" : ""}</span>
      <b>{label}</b>
    </span>
  );
}
