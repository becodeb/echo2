"""Acta de entrevista con formulario fijo (colegios).

Un colegio no quiere "un acta en markdown": quiere SU formulario, el que
imprime y firma la familia, con los mismos campos en el mismo lugar. Cuando
el modelo de acta de la organización es el de entrevista (tiene `{{alumno}}`),
el generador no redacta texto libre: completa estos campos, que viajan en
`MinutesVersion.blocks` y la hoja de impresión dibuja sobre el formulario.

El markdown se sigue guardando, armado acá a partir de los campos, porque de
él viven la búsqueda, el chat y las exportaciones.

Hay dos formularios, según el modelo de acta de cada sede:
- "entrevista" (Puertos): alumno, curso, solicitada por y motivo arriba, el
  párrafo fijo y el desarrollo sobre renglones.
- "reunion" (Nordelta, modelo con `{{hora}}`): "ACTA DE REUNIÓN" en prosa;
  "A los … días … siendo las HH:MM hs, se reúnen {familia} con {colegio}.",
  el desarrollo y el cierre fijo de lectura y firma.
"""
import re
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
FORMATOS = ("entrevista", "reunion")
_HORA_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")

# Cierre del acta de reunión: va siempre igual, lo pone la hoja y no la IA.
CIERRE_REUNION = (
    "Sin más temas que abordar, se da por finalizada la reunión.",
    "Previa lectura por las partes, y estando todos de acuerdo con su contenido, se firma el presente documento.",
)

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

FIELDS_SPEC_REUNION = """Campos del acta de reunión (todos texto plano):
- "alumno": apellido y nombre del estudiante del que se habla ("APELLIDO, Nombre" si se sabe).
- "curso": curso o grado (ej. "6to Eco.", "3N EP").
- "motivo": motivo general en pocas palabras (ej. "Acreditación de materias").
- "con": quiénes vienen por la familia u otros, con nombre y vínculo
  (ej. "la Sra. Roxana Pérez, madre del estudiante Tomás Pérez").
- "reunen": quiénes participan por el colegio, con nombre y cargo
  (ej. "Natalia Miranda, Directora del Nivel, y Rocío Gómez, Tutora de 6to Eco.").
- "desarrollo": el cuerpo del acta en prosa, en párrafos separados por una
  línea en blanco. Empezá con el propósito ("En el día de la fecha, se convoca
  a la familia de … para …") y seguí con lo que planteó cada parte, tema por
  tema ("En relación con …"), acuerdos y compromisos con responsable y fecha.
  NO escribas el cierre ("Sin más temas que abordar…" ni "Previa lectura…"):
  lo agrega el formulario."""


def initials(name: str) -> str:
    """Iniciales del alumno para el acta: "MUNAFO, Allegra" o "Allegra Munafo" → "A. M.".

    El acta lleva solo las iniciales (pedido de Northfield, 26/10): el nombre
    completo queda en Echo pero no sale impreso.
    """
    name = " ".join((name or "").split())
    if "," in name:
        surnames, given = name.split(",", 1)
        words = given.split() + surnames.split()
    else:
        words = name.split()
    return " ".join(f"{word[0].upper()}." for word in words if word[:1].isalpha())


def hide_student_names(text: str, students: list[tuple[str, str]]) -> str:
    """Reemplaza en el texto del acta cada forma del nombre del alumno por sus iniciales.

    `students`: [(nombre como se cargó, iniciales)]. Cubre "Nombre Apellido",
    "APELLIDO, Nombre", "Apellido" solo y "Nombre" solo, sin distinguir mayúsculas.
    """
    for full, short in students:
        full = " ".join(full.split())
        if "," in full:
            surnames, given = (part.strip() for part in full.split(",", 1))
        else:
            parts = full.split()
            given, surnames = " ".join(parts[:1]), " ".join(parts[1:])
        variants = [full, f"{given} {surnames}".strip(), f"{surnames}, {given}".strip(", "), surnames, given]
        for variant in sorted({v for v in variants if len(v) >= 3}, key=len, reverse=True):
            text = re.sub(rf"(?<!\w){re.escape(variant)}(?!\w)", short, text, flags=re.IGNORECASE)
    return text


def is_interview_template(body_markdown: str | None) -> bool:
    return "{{alumno}}" in (body_markdown or "")


def template_format(body_markdown: str | None) -> str:
    """Qué formulario pide el modelo de acta: el de reunión lleva la hora."""
    return "reunion" if "{{hora}}" in (body_markdown or "") else "entrevista"


def fields_spec(formato: str) -> str:
    return FIELDS_SPEC_REUNION if formato == "reunion" else FIELDS_SPEC


def meeting_time(started_at: datetime | None) -> str:
    moment = started_at or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(ARGENTINA).strftime("%H:%M")


def meeting_date(started_at: datetime | None) -> date:
    moment = started_at or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(ARGENTINA).date()


def normalize_fields(raw: dict | None, fallback_date: date, fallback_time: str = "") -> dict:
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
    # Las actas de antes no traen formato: eran todas de entrevista.
    formato = str(raw.get("formato") or "").strip().lower()
    out["formato"] = formato if formato in FORMATOS else "entrevista"
    if out["formato"] == "reunion":
        hora = _HORA_RE.match(str(raw.get("hora") or "").strip())
        out["hora"] = f"{int(hora.group(1)):02d}:{hora.group(2)}" if hora else fallback_time
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
    if fields.get("formato") == "reunion":
        hora = f", siendo las {fields['hora']} hs" if fields.get("hora") else ""
        parts = [
            "# ACTA DE REUNIÓN",
            f"A los {fecha.day} días del mes de {MESES[fecha.month - 1]} del {fecha.year} en la sede de la "
            f"institución{hora}, se reúnen {fields['con'] or blank} con {fields['reunen'] or blank}"
            f"{'' if fields['reunen'].endswith(('.', ':')) else '.'}",
            fields["desarrollo"],
            *CIERRE_REUNION,
        ]
        return "\n\n".join(part for part in parts if part) + "\n"
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
