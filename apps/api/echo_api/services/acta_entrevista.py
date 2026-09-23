"""Acta de entrevista con formulario fijo (colegios).

Un colegio no quiere "un acta en markdown": quiere SU formulario, el que
imprime y firma la familia, con los mismos campos en el mismo lugar. Cuando
el modelo de acta de la organización es el de entrevista (tiene `{{alumno}}`),
el generador no redacta texto libre: completa estos campos, que viajan en
`MinutesVersion.blocks` y la hoja de impresión dibuja sobre el formulario.

El markdown se sigue guardando, armado acá a partir de los campos, porque de
él viven la búsqueda, el chat y las exportaciones.
"""
from datetime import date, datetime, timedelta, timezone

KIND = "entrevista"

# Argentina no tiene horario de verano: un offset fijo alcanza y no depende
# de que la imagen traiga la base de zonas horarias.
ARGENTINA = timezone(timedelta(hours=-3))

MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)

TEXT_FIELDS = ("alumno", "curso", "motivo", "reunen", "con", "desarrollo")
SOLICITANTES = ("familia", "colegio")

GENERATOR_SYSTEM = """Sos el redactor de actas de entrevista de un colegio. Completás los campos
del formulario institucional usando EXCLUSIVAMENTE lo que surge del transcript
y de los datos provistos.

REGLAS CRÍTICAS:
1. NO INVENTES. Un nombre, curso o motivo que no se mencionó queda vacío ("").
2. Registro formal de acta escolar, tercera persona, pasado ("La familia
   manifiesta...", "Se acuerda..."). Nada de viñetas ni markdown en los campos.
3. Escribí en {language}."""

FIELDS_SPEC = """Campos del formulario (todos texto plano):
- "alumno": apellido y nombre del alumno/a ("APELLIDO, Nombre" si se sabe).
- "curso": curso o grado (ej. "3N EP", "5to grado").
- "solicitada_por": "familia" o "colegio" según quién pidió la entrevista; "" si no surge.
- "motivo": motivo general en pocas palabras (ej. "Actitudinal", "Seguimiento pedagógico").
- "reunen": quiénes se reúnen por la institución, con nombre y cargo
  (ej. "la Directora Mariana Gibson y la docente Sonia Albertin").
- "con": con quiénes, por la familia u otros (ej. "la Sra. Melina Larrubia, madre del alumno").
- "desarrollo": el cuerpo del acta en prosa, en párrafos: qué se planteó, qué
  dijo cada parte, acuerdos, compromisos con responsable y fecha, próxima
  entrevista si se fijó. Cerrá con "Sin más asuntos que tratar, se da por
  finalizada la entrevista, firmando al pie los presentes en conformidad."."""


def is_interview_template(body_markdown: str | None) -> bool:
    return "{{alumno}}" in (body_markdown or "")


def meeting_date(started_at: datetime | None) -> date:
    moment = started_at or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(ARGENTINA).date()


def normalize_fields(raw: dict | None, fallback_date: date) -> dict:
    """Deja los campos con forma conocida, pase lo que pase en la entrada.

    Tanto el LLM como el formulario de la web pueden mandar de más, de menos
    o con otro tipo: la hoja impresa no puede depender de eso.
    """
    raw = raw if isinstance(raw, dict) else {}
    out: dict = {}
    for key in TEXT_FIELDS:
        value = raw.get(key)
        out[key] = str(value).strip() if value is not None else ""
    solicitada = str(raw.get("solicitada_por") or "").strip().lower()
    out["solicitada_por"] = solicitada if solicitada in SOLICITANTES else ""
    try:
        out["fecha"] = date.fromisoformat(str(raw.get("fecha"))).isoformat()
    except ValueError:
        out["fecha"] = fallback_date.isoformat()
    return out


def to_blocks(fields: dict) -> dict:
    return {"kind": KIND, "fields": fields}


def fields_from_blocks(blocks) -> dict | None:
    if isinstance(blocks, dict) and blocks.get("kind") == KIND and isinstance(blocks.get("fields"), dict):
        return blocks["fields"]
    return None


def render_markdown(fields: dict) -> str:
    """El acta como texto, para búsqueda, chat y exportaciones."""
    fecha = date.fromisoformat(fields["fecha"])
    blank = "……………"
    solicitada = {"familia": "Familia", "colegio": "Colegio"}.get(fields["solicitada_por"], blank)
    parts = [
        "# ACTA DE ENTREVISTA",
        "",
        f"**Nombre del alumno:** {fields['alumno'] or blank}   **Curso:** {fields['curso'] or blank}",
        "",
        f"**Solicitada por:** {solicitada}",
        "",
        f"**Motivo general:** {fields['motivo'] or blank}",
        "",
        f"A los {fecha.day} días del mes de {MESES[fecha.month - 1]} de {fecha.year}, "
        f"en las instalaciones de la institución, se reúnen {fields['reunen'] or blank} "
        f"con {fields['con'] or blank}.",
        "",
        fields["desarrollo"] or "",
    ]
    return "\n".join(parts).rstrip() + "\n"
