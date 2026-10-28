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

El membrete puede fijar, por nivel (inicial / primaria / secundaria), el
formulario y cómo se nombra al colegio (`letterhead["levels"]`). Con la frase
cargada, el de entrevista sale como la planilla del jardín: "A los … días del
mes de … de …, se reúnen {reunen} {frase} con: {con}", y el motivo va después
del párrafo. Sin nada cargado sale como siempre.
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
SOLICITANTES = ("familia", "colegio", "equipo")
FORMATOS = ("entrevista", "reunion")
NIVELES = ("inicial", "primaria", "secundaria")
MAX_FRASE = 300
MODALIDADES = ("presencial", "remota")
MAX_LINEAS = 8
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
- "solicitada_por": "familia", "colegio" (la escuela) o "equipo" (equipo de profesionales)
  según quién pidió la entrevista; "" si no surge.
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


def normalize_levels(raw) -> dict[str, dict[str, str]]:
    """Lo que el membrete fija por nivel: {nivel: {"format", "school", "lines"}}.

    Vacío ("", []) quiere decir "como siempre": el formulario lo decide el
    modelo de acta, el párrafo no nombra al colegio y el encabezado es el de la sede.
    """
    raw = raw if isinstance(raw, dict) else {}
    out: dict[str, dict[str, str]] = {}
    for nivel in NIVELES:
        item = raw.get(nivel)
        item = item if isinstance(item, dict) else {}
        formato = str(item.get("format") or "").strip().lower()
        lines = item.get("lines") if isinstance(item.get("lines"), list) else []
        out[nivel] = {
            "format": formato if formato in FORMATOS else "",
            "school": " ".join(str(item.get("school") or "").split())[:MAX_FRASE],
            "lines": [" ".join(str(line).split())[:120] for line in lines if str(line).strip()][:MAX_LINEAS],
        }
    return out


def level_settings(letterhead: dict | None, nivel: str | None) -> dict:
    """Formato, frase del colegio y encabezado de ese nivel (todo vacío si no hay nada)."""
    levels = normalize_levels((letterhead or {}).get("levels"))
    return levels.get(nivel or "", {"format": "", "school": "", "lines": []})


def configured_level(letterhead: dict | None, nivel: str | None) -> str:
    """El nivel, si el membrete le fijó algo; si no, "" (la hoja sale como siempre)."""
    settings = level_settings(letterhead, nivel)
    return nivel if nivel and (settings["format"] or settings["school"] or settings["lines"]) else ""


def modalidad_text(modalidad: str | None) -> str:
    """"de manera presencial"; sin dato, las dos opciones del papel para tachar a mano."""
    return f"de manera {modalidad}" if modalidad in MODALIDADES else "de manera remota / presencial"


def curso_label(nivel: str | None) -> str:
    return "Kinder" if nivel == "inicial" else "Curso"


def solicitante_labels(nivel: str | None) -> dict[str, str]:
    return {
        "familia": "Familia",
        "colegio": "Escuela" if nivel == "inicial" else "Colegio",
        "equipo": "Equipo de profesionales",
    }


def fields_spec(formato: str, nivel: str | None = None, frase: str = "") -> str:
    if formato == "reunion":
        return FIELDS_SPEC_REUNION
    spec = FIELDS_SPEC
    if nivel == "inicial":
        spec = spec.replace(
            '- "curso": curso o grado (ej. "3N EP", "5to grado").',
            '- "curso": sala (ej. "3 F"; el formulario dice "Kinder").',
        )
    if frase:
        spec = spec.replace(
            "(ej. \"la Directora Mariana Gibson y la docente Sonia Albertin\").",
            "(ej. \"la Directora Mariana Gibson y la docente Sonia Albertin\"). No nombres al\n"
            "  colegio: el formulario lo agrega después.",
        )
    return spec


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
    # Cómo fue la reunión ("de manera presencial / remota"); sin dato, no viaja.
    modalidad = str(raw.get("modalidad") or "").strip().lower()
    if modalidad in MODALIDADES:
        out["modalidad"] = modalidad
    # El nivel solo viaja cuando el membrete le fijó algo: las actas de antes
    # y las de sedes sin configurar siguen igual.
    nivel = str(raw.get("nivel") or "").strip().lower()
    if nivel in NIVELES:
        out["nivel"] = nivel
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


def render_markdown(fields: dict, letterhead: dict | None = None) -> str:
    """El acta como texto, para búsqueda, chat y exportaciones.

    Con el membrete, el texto nombra al colegio como lo hace la hoja (la frase
    del nivel o el lugar de la sede) en vez de "la institución".
    """
    fecha = date.fromisoformat(fields["fecha"])
    blank = "……………"
    nivel = fields.get("nivel")
    school = level_settings(letterhead, nivel)["school"]
    lugar = ((letterhead or {}).get("interview_place") or "").strip()
    if fields.get("formato") == "reunion":
        hora = f", siendo las {fields['hora']} hs" if fields.get("hora") else ""
        sede = school or lugar or "la sede de la institución"
        parts = [
            "# ACTA DE REUNIÓN",
            f"A los {fecha.day} días del mes de {MESES[fecha.month - 1]} del {fecha.year} en {sede}"
            f"{hora}, se reúnen {fields['con'] or blank} con {fields['reunen'] or blank}"
            f"{'' if fields['reunen'].endswith(('.', ':')) else '.'}",
            fields["desarrollo"],
            *CIERRE_REUNION,
        ]
        return "\n\n".join(part for part in parts if part) + "\n"
    solicitada = solicitante_labels(nivel).get(fields["solicitada_por"], blank)
    if school:
        # Como la planilla en papel: el motivo va después del párrafo.
        parts = [
            "# ACTA DE ENTREVISTA",
            "",
            f"**Nombre del alumno:** {fields['alumno'] or blank}   **{curso_label(nivel)}:** {fields['curso'] or blank}",
            "",
            f"**Solicitada por:** {solicitada}",
            "",
            f"A los {fecha.day} días del mes de {MESES[fecha.month - 1]} de {fecha.year}, "
            f"se reúnen {modalidad_text(fields.get('modalidad'))} {fields['reunen'] or blank} {school} "
            f"con: {fields['con'] or blank}",
            "",
            f"**Motivo de la reunión:** {fields['motivo'] or blank}",
            "",
            fields["desarrollo"] or "",
        ]
        return "\n".join(parts).rstrip() + "\n"
    parts = [
        "# ACTA DE ENTREVISTA",
        "",
        f"**Nombre del alumno:** {fields['alumno'] or blank}   **{curso_label(nivel)}:** {fields['curso'] or blank}",
        "",
        f"**Solicitada por:** {solicitada}",
        "",
        f"**Motivo general:** {fields['motivo'] or blank}",
        "",
        f"A los {fecha.day} días del mes de {MESES[fecha.month - 1]} de {fecha.year}, "
        f"en las instalaciones de {lugar or 'la institución'}, se reúnen {fields['reunen'] or blank} "
        f"con {fields['con'] or blank}.",
        "",
        fields["desarrollo"] or "",
    ]
    return "\n".join(parts).rstrip() + "\n"
