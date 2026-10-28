import type { CSSProperties } from "react";
import type { InterviewFields, LetterheadOut } from "../api/types";
import { actaFormatVars, actaScale, levelLines } from "./actaFormat";
import "./interview-sheet.css";

const MESES = [
  "enero", "febrero", "marzo", "abril", "mayo", "junio",
  "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
];

/** Renglones vacíos mínimos: la hoja llega al pie aunque el acta sea corta. */
const MIN_RULED_LINES = 16;
const JARDIN_RULED_LINES = 13;
/** Alto del renglón del formulario con la letra de siempre. */
const RULED_LINE_PT = 20;

/**
 * Letra, interlineado y márgenes de la sede, y el alto de los renglones. Con
 * letra más grande los renglones crecen con ella y el espacio rayado mínimo se
 * achica (por la escala al cuadrado: lo de arriba también crece). Medido con
 * membrete y logo: un acta corta en "muy grande" ocupa 268 de los 297 mm.
 */
function sheetFormat(letterhead: LetterheadOut, minLines = MIN_RULED_LINES) {
  const { scale, line } = actaScale(letterhead);
  const ruled = Math.round(RULED_LINE_PT * scale * line * 100) / 100;
  const lines = Math.max(6, Math.floor((minLines * RULED_LINE_PT) / scale ** 2 / ruled));
  return {
    style: { ...actaFormatVars(letterhead), "--ent-renglon": `${ruled}pt` } as CSSProperties,
    minRuledHeight: `${lines * ruled}pt`,
  };
}

/** Cómo el membrete nombra al colegio para el nivel del acta ("" si no hay frase cargada). */
function levelSchool(fields: InterviewFields, letterhead: LetterheadOut): string {
  return (fields.nivel && letterhead.levels?.[fields.nivel]?.school) || "";
}

/**
 * El formulario "Acta de entrevista" del colegio, completo. Replica el papel:
 * membrete gris, logo centrado, campos punteados, casilleros Familia/Colegio,
 * el párrafo fijo y el desarrollo sobre renglones. Es lo que se imprime.
 */
export function InterviewSheet({
  fields,
  letterhead,
  number = null,
}: {
  fields: InterviewFields;
  letterhead: LetterheadOut;
  /** Número de acta; sin número (todavía no se imprimió) no se muestra. */
  number?: number | null;
}) {
  if (fields.formato === "reunion") return <ReunionSheet fields={fields} letterhead={letterhead} number={number} />;
  // Con la frase del colegio cargada para el nivel, la hoja es la planilla del
  // papel (jardín de Nordelta), con su propia maqueta.
  const school = levelSchool(fields, letterhead);
  if (school) return <JardinSheet fields={fields} letterhead={letterhead} number={number} school={school} />;
  const [year, month, day] = fields.fecha.split("-").map(Number);
  const place = letterhead.interview_place || `la institución ${letterhead.institution}`;
  const paragraphs = fields.desarrollo.split(/\n\s*\n|\n/).map((text) => text.trim()).filter(Boolean);
  const format = sheetFormat(letterhead);
  const inicial = fields.nivel === "inicial";

  return (
    <article className="entrevista-hoja" style={format.style}>
      {number != null && <p className="ent-numero">Acta N.º {number}</p>}
      <header className="ent-membrete">
        {levelLines(letterhead, fields.nivel).map((line, index) => (
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
        <b className="ent-curso">{inicial ? "Kinder:" : "Curso:"}</b>
        <Fill className="ent-corto">{fields.curso}</Fill>
      </p>

      <p className="ent-fila ent-solicitada">
        <b>Solicitada por:</b>
      </p>
      <p className="ent-checks">
        {inicial && <Check checked={fields.solicitada_por === "colegio"} label="Escuela" />}
        <Check checked={fields.solicitada_por === "familia"} label="Familia" />
        {!inicial && <Check checked={fields.solicitada_por === "colegio"} label="Colegio" />}
        {(inicial || fields.solicitada_por === "equipo") && (
          <Check checked={fields.solicitada_por === "equipo"} label="Equipo de profesionales" />
        )}
      </p>

      <p className="ent-fila ent-motivo">
        <b>Motivo general :</b>
        <Fill className="ent-grow">{fields.motivo}</Fill>
      </p>

      <p className="ent-parrafo">
        A los <Fill>{day ? String(day) : ""}</Fill> días del mes de <Fill>{month ? MESES[month - 1] : ""}</Fill> de{" "}
        {year || "……"} en las instalaciones de {place}, se reúnen <Fill>{fields.reunen}</Fill>
      </p>

      <div className="ent-renglones" style={{ minHeight: format.minRuledHeight }}>
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

/** La frase del colegio con lo que va en negrita en el papel: "del **Colegio … registro de DIEGEP N° …** de nivel inicial". */
function splitSchool(phrase: string): [string, string, string] {
  const match = /^(del\s+)?(.*?)(\s+de nivel\s+\S+)?$/i.exec(phrase.trim());
  return match ? [match[1] ?? "", match[2], match[3] ?? ""] : ["", phrase, ""];
}

/**
 * La planilla de entrevista del jardín de Nordelta, como la hoja en papel: logo
 * a la izquierda con "Folio Nro" a su derecha, membrete en mayúsculas debajo,
 * "Kinder" en su renglón, tres casilleros y el párrafo corrido sobre líneas de
 * guiones, con "de manera remota / presencial" para tachar la que no va.
 */
function JardinSheet({
  fields,
  letterhead,
  number,
  school,
}: {
  fields: InterviewFields;
  letterhead: LetterheadOut;
  number: number | null;
  school: string;
}) {
  const [year, month, day] = fields.fecha.split("-").map(Number);
  const paragraphs = fields.desarrollo.split(/\n\s*\n|\n/).map((text) => text.trim()).filter(Boolean);
  // Con el logo y el párrafo corrido arriba, 13 renglones dejan la hoja en un A4.
  const format = sheetFormat(letterhead, JARDIN_RULED_LINES);
  const [pre, bold, post] = splitSchool(school);
  // El papel trae "20" impreso: el blanco son los dos últimos dígitos.
  const yearEnd = year ? String(year % 100).padStart(2, "0") : "";
  const strike = (mode: "remota" | "presencial") => (fields.modalidad && fields.modalidad !== mode ? "jar-tachado" : "");

  return (
    <article className="entrevista-hoja jardin-hoja" style={format.style}>
      <div className="jar-cabecera">
        {letterhead.logo_data_url ? (
          <img src={letterhead.logo_data_url} alt={letterhead.institution} className="jar-logo" />
        ) : (
          <span />
        )}
        <p className="jar-folio">
          Folio Nro: {number != null ? <b>{number}</b> : <span className="ent-folio-vacio" />}
        </p>
      </div>
      <header className="jar-membrete">
        {levelLines(letterhead, fields.nivel).map((line, index) => (
          <p key={index}>{line}</p>
        ))}
      </header>
      {/* La planilla del nivel es siempre de entrevista, aunque el membrete de la
          sede diga otro título (Nordelta: "ACTA DE REUNIÓN" en los otros niveles). */}
      <h1 className="ent-titulo jar-titulo">ACTA DE ENTREVISTA</h1>

      <p className="jar-fila jar-primera">
        Nombre del alumno/a: <Blank className="jar-ancho">{fields.alumno}</Blank>
      </p>
      <p className="jar-fila">
        {fields.nivel === "inicial" ? "Kinder:" : "Curso:"} <Blank className="jar-corto">{fields.curso}</Blank>
      </p>

      <p className="jar-fila jar-solicitada">Solicitada por:</p>
      <p className="jar-checks">
        <Check checked={fields.solicitada_por === "colegio"} label="Escuela" />
        <Check checked={fields.solicitada_por === "familia"} label="Familia" />
        <Check checked={fields.solicitada_por === "equipo"} label="Equipo de profesionales" />
      </p>

      <p className="jar-parrafo">
        A los <Blank className="jar-dia">{day ? String(day) : ""}</Blank> días del mes de{" "}
        <Blank className="jar-mes">{month ? MESES[month - 1] : ""}</Blank> de 20
        <Blank className="jar-anio">{yearEnd}</Blank>, se reúnen de manera <span className={strike("remota")}>remota</span> /{" "}
        <span className={strike("presencial")}>presencial</span> <Blank className="jar-largo">{fields.reunen}</Blank> {pre}
        <b>{bold}</b>
        {post} con: <Blank className="jar-largo">{fields.con}</Blank>
      </p>

      <div className="ent-renglones jar-renglones" style={{ minHeight: format.minRuledHeight }}>
        <p>Motivo de la reunión: {fields.motivo}</p>
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

function Blank({ children, className = "" }: { children: string; className?: string }) {
  // Como en el papel: una línea de guiones para completar a mano.
  return <span className={`jar-fill ${children ? "" : "jar-vacio"} ${className}`}>{children || " "}</span>;
}

/**
 * El "Acta de reunión" de Nordelta: membrete a la izquierda y logo a la
 * derecha, título centrado y todo en prosa justificada, con el cierre fijo de
 * lectura y firma. Sin renglones ni casilleros: así es el Word del colegio.
 */
function ReunionSheet({
  fields,
  letterhead,
  number,
}: {
  fields: InterviewFields;
  letterhead: LetterheadOut;
  number: number | null;
}) {
  const [year, month, day] = fields.fecha.split("-").map(Number);
  const place = levelSchool(fields, letterhead) || letterhead.interview_place || `la sede de ${letterhead.institution}`;
  const paragraphs = fields.desarrollo.split(/\n\s*\n|\n/).map((text) => text.trim()).filter(Boolean);
  // Sin etiquetas cargadas, igual van las dos líneas de firma del modelo.
  const signatures = letterhead.signatures.length > 0 ? letterhead.signatures : ["", ""];

  return (
    <article className="entrevista-hoja reunion-hoja" style={sheetFormat(letterhead).style}>
      {number != null && <p className="ent-numero">Acta N.º {number}</p>}
      <header className="reu-encabezado">
        <div className="reu-membrete">
          {levelLines(letterhead, fields.nivel).map((line, index) => (
            <p key={index}>{line}</p>
          ))}
        </div>
        {letterhead.logo_data_url && (
          <img src={letterhead.logo_data_url} alt={letterhead.institution} className="reu-logo" />
        )}
      </header>
      <h1 className="ent-titulo reu-titulo">{letterhead.title || "ACTA DE REUNIÓN"}</h1>

      <div className="reu-cuerpo">
        <p>
          A los <Fill>{day ? String(day) : ""}</Fill> días del mes de <Fill>{month ? MESES[month - 1] : ""}</Fill> del{" "}
          {year || "……"} en {place}, siendo las <Fill>{fields.hora ?? ""}</Fill> hs, se reúnen <Fill>{fields.con}</Fill>{" "}
          con <Fill>{fields.reunen}</Fill>
          {/[.:]$/.test(fields.reunen) ? "" : "."}
        </p>
        {paragraphs.map((text, index) => (
          <p key={index}>{text}</p>
        ))}
        <p>Sin más temas que abordar, se da por finalizada la reunión.</p>
        <p>Previa lectura por las partes, y estando todos de acuerdo con su contenido, se firma el presente documento.</p>
      </div>

      <footer className="ent-firmas reu-firmas">
        {signatures.map((label, index) => (
          <span key={index}>{label}</span>
        ))}
      </footer>
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
