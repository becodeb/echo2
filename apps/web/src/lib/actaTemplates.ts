/**
 * Modelos de acta listos para cargar en Ajustes → Formato de acta. Cada uno
 * es Markdown con campos entre llaves; el generador los completa con lo que
 * se dijo y deja "No especificado durante la reunión" donde no hay datos.
 */

/** Acta de entrevista de una institución educativa (familia, docente, equipo). */
export const ACTA_ENTREVISTA_COLEGIO = `# ACTA DE ENTREVISTA

**Nombre del alumno/a:** {{alumno}}   **Curso:** {{curso}}

**Solicitada por:** {{solicitada_por}} (Familia / Colegio)

**Motivo general:** {{motivo}}

A los {{dia}} días del mes de {{mes}} de {{anio}}, en las instalaciones de la institución, se reúnen {{participantes_institucion}} con {{participantes_familia}}.

## Desarrollo de la entrevista
{{desarrollo}}

## Acuerdos
{{acuerdos}}

## Compromisos
| Compromiso | Responsable | Fecha |
|------------|-------------|-------|
{{compromisos}}

## Próxima entrevista
{{proxima_entrevista}}

Sin más asuntos que tratar, se da por finalizada la entrevista, firmando al pie los presentes en conformidad.
`;
