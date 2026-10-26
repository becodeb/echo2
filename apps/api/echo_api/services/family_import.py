"""Cargar alumnos y familias desde la planilla del colegio (CSV).

Pedido de la capacitación (26/10): cargar kinder, primaria y secundaria a mano
no es viable. Se sube el CSV que ya usan (exportado de Excel o de Google
Sheets) y Echo arma las familias con sus hijos, curso y nivel.

Las columnas se reconocen por nombre, sin importar mayúsculas ni tildes:
- alumno / estudiante / nombre y apellido   (o "apellido" + "nombre" por separado)
- curso / grado / división / sala
- nivel (inicial|kinder|jardín, primaria, secundaria; si falta se deduce del curso)
- familia (opcional: agrupa hermanos aunque no compartan apellido)
- madre, padre, tutor / responsable, email / mail, teléfono / celular (opcionales)

Hermanos: sin columna "familia" se agrupan por apellido y responsable (el mail
o el nombre de la madre/padre/tutor); sin responsable, por apellido. Una
familia que ya existe en la sede con ese nombre se completa, no se duplica, y
un integrante que ya está no se vuelve a cargar.
"""
import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field

MAX_ROWS = 5000


def _key(text: str) -> str:
    plain = unicodedata.normalize("NFD", (text or "").strip().lower())
    return "".join(char for char in plain if unicodedata.category(char) != "Mn")


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


COLUMNS = {
    "alumno": ("alumno", "alumna", "estudiante", "nombre y apellido", "apellido y nombre", "nombre completo", "alumno/a"),
    "apellido": ("apellido", "apellidos"),
    "nombre": ("nombre", "nombres"),
    "curso": ("curso", "grado", "division", "sala", "curso/division", "grado/curso"),
    "nivel": ("nivel", "seccion", "ciclo"),
    "familia": ("familia", "grupo familiar"),
    "madre": ("madre", "mama", "nombre madre", "nombre de la madre"),
    "padre": ("padre", "papa", "nombre padre", "nombre del padre"),
    "tutor": ("tutor", "tutora", "responsable", "adulto responsable"),
    "email": ("email", "mail", "e-mail", "correo", "email responsable", "mail familia"),
    "telefono": ("telefono", "celular", "tel", "whatsapp"),
}


_LEVEL_WORDS = (
    ("inicial", r"\b(inicial|kinder|jardin|sala|ei|preescolar)\b"),
    ("secundaria", r"\b(secundaria|es|media|polimodal|ano)\b"),
    ("primaria", r"\b(primaria|ep|grado)\b"),
)


def _level(raw: str, curso: str) -> str | None:
    """El nivel de la columna "nivel" y, si no está, el que dice el curso ("3N EP", "Sala 5")."""
    for text in (_key(raw), _key(curso)):
        for level, pattern in _LEVEL_WORDS:
            if text and re.search(pattern, text):
                return level
    return None


@dataclass
class ImportedFamily:
    name: str
    students: list[dict] = field(default_factory=list)  # {name, curso, level}
    guardians: list[dict] = field(default_factory=list)  # {name, relationship_type, email, phone}


@dataclass
class ParsedImport:
    families: list[ImportedFamily]
    skipped: int
    columns: dict[str, str]


def parse_csv(data: bytes) -> ParsedImport:
    """Arma las familias del CSV. Levanta ValueError con un mensaje para mostrar."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")  # Excel en castellano guarda así
    if not text.strip():
        raise ValueError("El archivo está vacío.")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.reader(io.StringIO(text), dialect)
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if len(rows) < 2:
        raise ValueError("El archivo no tiene filas además de los títulos.")
    if len(rows) > MAX_ROWS + 1:
        raise ValueError(f"El archivo tiene más de {MAX_ROWS} filas: dividilo en partes.")

    header = [_key(cell) for cell in rows[0]]
    columns: dict[str, int] = {}
    for field_name, names in COLUMNS.items():
        for index, title in enumerate(header):
            if title in names and index not in columns.values():
                columns[field_name] = index
                break
    if "alumno" not in columns and "apellido" not in columns:
        raise ValueError(
            "No encontré la columna del alumno. Poné en la primera fila un título como "
            "«Alumno» (o «Apellido» y «Nombre»), y si querés «Curso», «Nivel», «Madre», «Padre», «Email»."
        )

    def cell(row: list[str], name: str) -> str:
        index = columns.get(name)
        return _clean(row[index]) if index is not None and index < len(row) else ""

    families: dict[str, ImportedFamily] = {}
    skipped = 0
    for row in rows[1:]:
        surname, given = cell(row, "apellido"), cell(row, "nombre")
        full = cell(row, "alumno")
        if not full and surname:
            full = f"{surname}, {given}" if given else surname
        if not full:
            skipped += 1
            continue
        if not surname:
            surname = full.split(",", 1)[0] if "," in full else full.split()[-1]
        curso = cell(row, "curso")
        guardians = [
            {"name": cell(row, kind), "relationship_type": kind}
            for kind in ("madre", "padre", "tutor")
            if cell(row, kind)
        ]
        email, phone = cell(row, "email"), cell(row, "telefono")
        explicit = cell(row, "familia")
        anchor = email.lower() or (guardians[0]["name"] if guardians else "")
        group = _key(explicit) if explicit else f"{_key(surname)}|{_key(anchor)}"
        family = families.get(group)
        if family is None:
            family = families[group] = ImportedFamily(name=explicit or f"Familia {surname.title() if surname.isupper() else surname}")
        if _key(full) not in {_key(s["name"]) for s in family.students}:
            family.students.append({"name": full, "curso": curso or None, "level": _level(cell(row, "nivel"), curso)})
        known = {_key(g["name"]) for g in family.guardians}
        for index, guardian in enumerate(guardians):
            if _key(guardian["name"]) in known:
                continue
            family.guardians.append(
                {**guardian, "email": (email or None) if index == 0 else None, "phone": (phone or None) if index == 0 else None}
            )

    # Dos familias distintas con el mismo apellido: se distinguen por su responsable.
    by_name: dict[str, list[ImportedFamily]] = {}
    for family in families.values():
        by_name.setdefault(_key(family.name), []).append(family)
    for same in by_name.values():
        if len(same) > 1:
            for family in same:
                if family.guardians:
                    family.name = f"{family.name} ({family.guardians[0]['name']})"

    return ParsedImport(
        families=list(families.values()),
        skipped=skipped,
        columns={name: rows[0][index] for name, index in columns.items()},
    )


async def apply_import(db, org_id, parsed: ParsedImport, write: bool) -> dict:
    """Crea o completa las familias. Con write=False solo cuenta (vista previa)."""
    from sqlalchemy import select

    from ..models import Family, FamilyMember

    existing = {
        _key(family.name): family
        for family in (
            await db.execute(select(Family).where(Family.organization_id == org_id, Family.deleted_at.is_(None)))
        ).scalars()
    }
    members: dict = {}
    if existing:
        for member in (
            await db.execute(
                select(FamilyMember).where(FamilyMember.family_id.in_([family.id for family in existing.values()]))
            )
        ).scalars():
            members.setdefault(member.family_id, set()).add(_key(member.name))

    counts = {"families_created": 0, "families_completed": 0, "students": 0, "guardians": 0}
    for imported in parsed.families:
        family = existing.get(_key(imported.name))
        known = members.get(family.id, set()) if family else set()
        new_students = [s for s in imported.students if _key(s["name"]) not in known]
        new_guardians = [g for g in imported.guardians if _key(g["name"]) not in known]
        if family is None:
            counts["families_created"] += 1
        elif new_students or new_guardians:
            counts["families_completed"] += 1
        counts["students"] += len(new_students)
        counts["guardians"] += len(new_guardians)
        if not write:
            continue
        if family is None:
            family = Family(organization_id=org_id, name=imported.name[:200])
            db.add(family)
            await db.flush()
            existing[_key(imported.name)] = family
        for student in new_students:
            db.add(FamilyMember(
                family_id=family.id, name=student["name"][:200], relationship_type="estudiante",
                is_guardian=False, curso=(student["curso"] or None) and student["curso"][:60], level=student["level"],
            ))
        for guardian in new_guardians:
            db.add(FamilyMember(
                family_id=family.id, name=guardian["name"][:200], relationship_type=guardian["relationship_type"]
                if guardian["relationship_type"] in ("madre", "padre") else "tutor",
                is_guardian=True, email=guardian.get("email"), phone=guardian.get("phone"),
            ))
    return counts
