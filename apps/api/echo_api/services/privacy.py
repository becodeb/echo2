"""Seudonimización: los nombres y datos personales no le llegan a la IA.

Antes de mandar texto a un proveedor externo (chat, embeddings), cada nombre
conocido se reemplaza por un marcador — "[ALUMNO_1]", "[MADRE_1]",
"[PERSONAL_2]" — y cada DNI, teléfono o email por "[NUMERO_1]" /
"[EMAIL_1]". La respuesta vuelve con marcadores y acá se les devuelve el
nombre real: lo que se guarda en Echo tiene nombres; lo que vio la IA, no.

De dónde salen los nombres: usuarios de la organización, familias y sus
integrantes, profesionales, participantes y hablantes de la reunión, y la
nómina protegida (`OrgProtectedName`, ej. el listado de alumnos del colegio).

Reglas de reconocimiento, pensadas para transcripts:

- Nombre completo ("Allegra Munafo", "MUNAFO, Allegra"): sin importar
  mayúsculas ni tildes.
- Palabra suelta ("Allegra", "Munafo"): solo si viene con mayúscula, que es
  como la escribe el transcriptor cuando es nombre propio. Así "campo" no se
  toca y "Campo" sí.
- Reemplazar de más es barato: la respuesta se restaura con el texto
  original, así que un "Pilar" (la ciudad) censurado por error solo cambia lo
  que lee la IA, no lo que queda escrito. Reemplazar de menos es lo que no
  puede pasar; por eso se prefiere ser agresivo.
- Un nombre de pila compartido por varias personas ("Martina") apunta a la de
  esta reunión si hay una sola; si no, lleva un marcador genérico
  "[NOMBRE_n]" que igual se restaura a lo que decía.
- Nombrar completo a un integrante de una familia (ej. el alumno) vuelve
  reconocibles al resto de esa familia por nombre de pila: "Melina" pasa a
  ser "[MADRE_1]" y no un genérico.

- Un nombre que no está en ninguna lista también se tapa si parece nombre
  propio: palabra con mayúscula a mitad de oración que en el mismo texto no
  aparece en minúscula ("¿Qué hacés, Bauti?"). Es local, sin mandar nada a
  nadie, y cubre la pasada con Groq (Gratis, reuniones con menores), donde no
  hay detección de entidades de Scribe. Va como "[NOMBRE_n]".
- Lo que Scribe detectó como dato personal o de salud (teléfono, dirección,
  diagnóstico, medicación) va como "[DATO_n]".

Lo que NO cubre: un nombre fuera de las listas dicho al principio de una
oración ("Bauti dijo que..."). Por eso importa cargar la nómina.
"""
from __future__ import annotations

import logging
import re
import time
import unicodedata
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .llm.base import LLMProvider, collect_usage

log = logging.getLogger("echo.privacy")

LABELS = {
    "alumno": "ALUMNO",
    "estudiante": "ALUMNO",
    "madre": "MADRE",
    "padre": "PADRE",
    "tutor": "TUTOR",
    "personal": "PERSONAL",
    "profesional": "PROFESIONAL",
    "persona": "PERSONA",
    "otro": "PERSONA",
}
ALL_LABELS = sorted(set(LABELS.values()) | {"NOMBRE", "NUMERO", "EMAIL", "DATO"})

# Palabras sueltas que no se toman como nombre aunque vengan con mayúscula:
# conectores de apellidos compuestos y palabras que abren oraciones.
STOPWORDS = {
    "de", "del", "la", "las", "los", "el", "y", "e", "da", "di", "van", "von", "san", "santa",
    "sr", "sra", "srta", "dr", "dra", "prof", "profe", "flia", "familia", "madre", "padre",
    "mama", "papa", "seno", "senor", "senora", "directora", "director", "docente", "maestra",
    "maestro", "alumno", "alumna", "hola", "bueno", "bien", "si", "no", "que", "como",
    # Meses y días: "Abril" o "Mercedes" existen como nombres, pero censurarlos
    # le saca a la IA las fechas de los compromisos.
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
    "setiembre", "octubre", "noviembre", "diciembre", "lunes", "martes", "miercoles", "jueves",
    "viernes", "sabado", "domingo",
}
MIN_SINGLE_WORD = 3

# Palabras que van con mayúscula a mitad de oración y no son nombres de
# persona. No hace falta que esté todo: tapar de más se restaura igual; esto
# es para que la IA no pierda contexto obvio de un colegio.
COMMON_CAPITALIZED = {
    "echo", "google", "drive", "meet", "zoom", "whatsapp", "gmail", "excel", "word", "classroom",
    "teams", "instagram", "facebook", "youtube", "internet", "covid", "dios", "virgen", "navidad",
    "pascua", "ministerio", "educacion", "argentina", "buenos", "aires", "provincia", "ciudad",
    "inicial", "primaria", "secundaria", "jardin", "nivel", "colegio", "escuela", "instituto",
    "universidad", "direccion", "secretaria", "consejo", "gabinete", "equipo", "orientacion",
    "psicopedagogia", "lengua", "matematica", "ingles", "historia", "geografia", "biologia",
    "fisica", "quimica", "musica", "plastica", "tecnologia", "ciencias", "naturales", "sociales",
    "semana", "dia", "acto", "face", "persona", "hablante", "participante", "reunion", "acta", "anexo",
}
# "Colegio Northfield", "Escuela San Martín": lo que sigue es el nombre de una
# institución, no de una persona.
INSTITUTION_WORDS = {
    "colegio", "escuela", "instituto", "jardin", "universidad", "club", "sede", "liceo", "fundacion",
    "hospital", "clinica", "parroquia", "empresa", "barrio", "calle", "avenida", "plaza", "parque",
}
# Lo que antecede a un comienzo de oración (ahí la mayúscula no dice nada).
_SENTENCE_START = set('.!?¿¡:;\n"«“(-•*>[]#|')

PRIVACY_NOTE = (
    "\n\nPrivacidad: los nombres propios y datos personales del texto fueron reemplazados por "
    "marcadores entre corchetes ([ALUMNO_1], [MADRE_1], [PERSONAL_2], [NOMBRE_3], [NUMERO_1]...). "
    "Cada marcador es una persona o dato concreto: usalo exactamente igual donde corresponda, "
    "incluso en los campos de nombre, y no intentes adivinar ni inventar el dato real."
)

_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?")
_SEPARATOR = re.compile(r"^[\s,]{1,3}$")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# 7+ dígitos, con puntos, guiones o espacios en el medio: DNI, CUIL, teléfonos.
# No toca valores numéricos de JSON ("evidencia_ms": 1234567): son milisegundos.
_NUMBER = re.compile(r'(?<![\w\[])(?<!": )(?<!":)\+?\d(?:[\d.\s-]{5,}\d)(?![\w\]])')
_DATE = re.compile(r"^\d{1,2}[-.]\d{1,2}[-.]\d{2,4}$")
_TOKEN = re.compile(r"\[?\b(" + "|".join(ALL_LABELS) + r")_(\d+)\b\]?", re.IGNORECASE)


def _nice(word: str) -> str:
    """"MUNAFO" → "Munafo", "Del" → "del": como se escribe en un acta."""
    if fold(word) in {"de", "del", "la", "las", "los", "y"}:
        return word.lower()
    return word.title() if word.isupper() else word


def fold(text: str) -> str:
    """minúsculas y sin tildes: "Muñoz" y "munoz" son la misma clave."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


@dataclass
class Person:
    display: str  # como se restaura: "Allegra Munafo"
    kind: str = "persona"
    group: str | None = None
    formal: str | None = None  # "MUNAFO, Allegra", para el campo del acta
    extra: dict = field(default_factory=dict)
    first_names: list[str] = field(default_factory=list)
    surnames: list[str] = field(default_factory=list)

    @classmethod
    def parse(cls, name: str, kind: str = "persona", group: str | None = None, extra: dict | None = None) -> Person | None:
        """Acepta "APELLIDO, Nombre" (nómina) o "Nombre Apellido" (lo demás)."""
        # "Analía Oliver - Northfield Puertos": lo que sigue al guion es un cargo
        # o una sede, no parte del nombre.
        name = " ".join((name or "").split(" - ")[0].split())
        if not name:
            return None
        if "," in name:
            last, _, first = (part.strip() for part in name.partition(","))
            surnames, first_names = last.split(), first.split()
            display = " ".join(_nice(w) for w in [*first_names, *surnames])
            return cls(display=display, kind=kind, group=group, formal=name, extra=extra or {},
                       first_names=first_names, surnames=surnames)
        words = name.split()
        return cls(display=name, kind=kind, group=group, extra=extra or {},
                   first_names=words[:1], surnames=words[1:])

    def full_variants(self) -> list[list[str]]:
        """Secuencias de palabras que nombran a la persona sin ambigüedad."""
        first, last = self.first_names, self.surnames
        variants = [self.display.split()]
        # Nombre de pila compuesto ("Maria del Pilar", "Feliciano Italo"): se
        # reconoce entero; si no, "Pilar" se reemplaza solo y queda "Maria del
        # [MADRE_1]", que al restaurar duplica el nombre.
        if len(first) >= 2:
            variants.append(first)
        if first and last:
            variants += [
                [*first, *last], [*last, *first], [first[0], *last], [*last, first[0]],
                [first[0], last[0]], [last[0], first[0]],
            ]
        return [v for v in variants if len(v) >= 2]

    def single_words(self) -> list[str]:
        return [w for w in [*self.first_names, *self.surnames]
                if len(fold(w)) >= MIN_SINGLE_WORD and fold(w) not in STOPWORDS]


class Pseudonymizer:
    """Reemplaza y restaura. Una instancia por reunión (o conversación): los
    marcadores son estables entre llamadas para que la IA no confunda a nadie.
    """

    def __init__(self, people: list[Person], priority_groups: set[str] | None = None,
                 priority_people: list[Person] | None = None, data: list[str] | None = None,
                 keep: set[str] | None = None):
        self.people = list(people) + list(priority_people or [])
        # Palabras que no se adivinan como nombre (las del nombre de la sede).
        self.keep = {fold(word) for word in keep or set()}
        # Datos que detectó Scribe (dirección, teléfono, diagnóstico...), tal cual se dijeron.
        literals = sorted({" ".join(d.split()) for d in data or [] if len(d.strip()) >= 3}, key=len, reverse=True)
        self._data = (
            re.compile(r"(?<!\w)(" + "|".join(re.escape(d) for d in literals) + r")(?!\w)", re.IGNORECASE)
            if literals else None
        )
        self.priority: set[int] = {len(people) + i for i in range(len(priority_people or []))}
        self.priority_groups = set(priority_groups or set())
        self._index: dict[tuple[str, ...], set[int]] = {}
        for idx, person in enumerate(self.people):
            for variant in person.full_variants():
                self._index.setdefault(tuple(fold(w) for w in variant), set()).add(idx)
            for word in person.single_words():
                self._index.setdefault((fold(word),), set()).add(idx)
        self._max_n = max((len(key) for key in self._index), default=1)
        self._person_token: dict[int, str] = {}
        self._generic_token: dict[str, str] = {}
        self._counters: dict[str, int] = {}
        self.restore_map: dict[str, str] = {}

    # ── marcadores ──────────────────────────────────────────────
    def _new_token(self, label: str, original: str) -> str:
        self._counters[label] = self._counters.get(label, 0) + 1
        token = f"[{label}_{self._counters[label]}]"
        self.restore_map[token] = original
        return token

    def _token_for_person(self, idx: int) -> str:
        if idx not in self._person_token:
            person = self.people[idx]
            self._person_token[idx] = self._new_token(LABELS.get(person.kind, "PERSONA"), person.display)
        return self._person_token[idx]

    def _token_for_generic(self, surface: str) -> str:
        key = fold(surface)
        if key not in self._generic_token:
            self._generic_token[key] = self._new_token("NOMBRE", surface)
        return self._generic_token[key]

    def person_for_token_text(self, text: str) -> Person | None:
        """La persona detrás de un nombre ya restaurado (para el campo alumno)."""
        for idx, token in self._person_token.items():
            if self.restore_map.get(token) == text:
                return self.people[idx]
        return None

    # ── reemplazo ───────────────────────────────────────────────
    def apply(self, text: str, guess: bool = True) -> str:
        """`guess`: tapar también lo que parece nombre aunque no esté en ninguna
        lista. Con instrucciones propias (el prompt del sistema) va en False."""
        if not text:
            return text
        text = _EMAIL.sub(lambda m: self._scrub_literal("EMAIL", m.group(0)), text)
        text = _NUMBER.sub(self._scrub_number, text)
        if self._data is not None:
            text = self._data.sub(lambda m: self._scrub_literal("DATO", m.group(0), fold_key=True), text)
        words = list(_WORD.finditer(text))
        self._promote(text, words)
        lowercase = {fold(w.group(0)) for w in words if w.group(0).islower()} if guess else set()
        out: list[str] = []
        cursor = 0
        i = 0
        while i < len(words):
            match = self._match_at(text, words, i)
            if match is None and guess:
                match = self._guess_at(text, words, i, lowercase)
            if match is None:
                i += 1
                continue
            n, token = match
            out.append(text[cursor:words[i].start()])
            out.append(token)
            cursor = words[i + n - 1].end()
            i += n
        out.append(text[cursor:])
        return "".join(out)

    def _scrub_literal(self, label: str, value: str, fold_key: bool = False) -> str:
        same = (lambda a, b: fold(a) == fold(b)) if fold_key else (lambda a, b: a == b)
        for token, original in self.restore_map.items():
            if same(original, value) and token.startswith(f"[{label}_"):
                return token
        return self._new_token(label, value)

    def _looks_like_name(self, word: str, lowercase: set[str]) -> bool:
        key = fold(word)
        return (
            len(key) >= MIN_SINGLE_WORD
            and key not in self.keep
            and word[:1].isupper()
            and not word.isupper()  # siglas y títulos en mayúsculas
            and key not in STOPWORDS
            and key not in COMMON_CAPITALIZED
            and key not in lowercase
        )

    def _guess_at(self, text: str, words: list[re.Match], i: int, lowercase: set[str]) -> tuple[int, str] | None:
        """Nombre propio fuera de las listas: mayúscula a mitad de oración."""
        if not self._looks_like_name(words[i].group(0), lowercase):
            return None
        before = text[:words[i].start()].rstrip(" \t")
        if not before or before[-1] in _SENTENCE_START or before[-1] == "\n":
            return None
        j = i - 1
        while j >= 0 and text[words[j].end():words[j + 1].start()] == " " and words[j].group(0)[:1].isupper():
            if fold(words[j].group(0)) in INSTITUTION_WORDS:
                return None
            j -= 1
        n = 1
        while (
            i + n < len(words)
            and text[words[i + n - 1].end():words[i + n].start()] == " "
            and self._looks_like_name(words[i + n].group(0), lowercase)
            and self._match_at(text, words, i + n) is None
        ):
            n += 1
        surface = text[words[i].start():words[i + n - 1].end()]
        return n, self._token_for_generic(surface)

    def _scrub_number(self, match: re.Match) -> str:
        value = match.group(0)
        digits = re.sub(r"\D", "", value)
        if len(digits) < 7 or _DATE.match(value.strip()):
            return value
        return self._scrub_literal("NUMERO", value)

    def _key(self, text: str, words: list[re.Match], i: int, n: int) -> tuple[str, ...] | None:
        if i + n > len(words):
            return None
        for a, b in zip(words[i:i + n - 1], words[i + 1:i + n]):
            if not _SEPARATOR.match(text[a.end():b.start()]):
                return None
        return tuple(fold(w.group(0)) for w in words[i:i + n])

    def _promote(self, text: str, words: list[re.Match]) -> None:
        """Un nombre completo en el texto vuelve prioritaria a su familia."""
        for i in range(len(words)):
            for n in range(self._max_n, 1, -1):
                key = self._key(text, words, i, n)
                if key and key in self._index:
                    for idx in self._index[key]:
                        self.priority.add(idx)
                        if self.people[idx].group:
                            self.priority_groups.add(self.people[idx].group)
                    break

    def _is_priority(self, idx: int) -> bool:
        return idx in self.priority or (self.people[idx].group in self.priority_groups)

    def _match_at(self, text: str, words: list[re.Match], i: int) -> tuple[int, str] | None:
        for n in range(self._max_n, 0, -1):
            key = self._key(text, words, i, n)
            if not key or key not in self._index:
                continue
            surface = text[words[i].start():words[i + n - 1].end()]
            if n == 1 and not surface[:1].isupper():
                return None
            candidates = self._index[key]
            if len(candidates) == 1:
                return n, self._token_for_person(next(iter(candidates)))
            preferred = [idx for idx in candidates if self._is_priority(idx)]
            # Varias personas "de esta reunión" con la misma clave también es
            # ambigüedad: marcador genérico antes que atribuirle algo a otra.
            if len(preferred) == 1:
                return n, self._token_for_person(preferred[0])
            return n, self._token_for_generic(surface)
        return None

    # ── restauración ────────────────────────────────────────────
    def restore(self, text: str) -> str:
        if not text or not self.restore_map:
            return text

        def put_back(match: re.Match) -> str:
            token = f"[{match.group(1).upper()}_{match.group(2)}]"
            return self.restore_map.get(token, match.group(0))

        return _TOKEN.sub(put_back, text)

    @property
    def used(self) -> bool:
        return bool(self.restore_map)


class PrivateLLMProvider(LLMProvider):
    """Envuelve a cualquier provider: seudonimiza lo que sale, restaura lo que vuelve."""

    def __init__(
        self,
        inner: LLMProvider,
        pseudonymizer: Pseudonymizer,
        org_id: uuid.UUID | None = None,
        meeting_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
    ):
        self.inner = inner
        self.pseudonymizer = pseudonymizer
        self.name = inner.name
        self.model = getattr(inner, "model", inner.name)
        # Para anotar los tokens en el panel de consumo (services/plans.py).
        self.org_id = org_id
        self.meeting_id = meeting_id
        self.user_id = user_id

    async def chat(self, system, messages, temperature=0.2, max_tokens=4096) -> str:
        p = self.pseudonymizer
        safe_messages = [{**m, "content": p.apply(m.get("content") or "")} for m in messages]
        safe_system = p.apply(system, guess=False)
        if p.used:
            safe_system += PRIVACY_NOTE
        with collect_usage() as used:
            answer = await self.inner.chat(safe_system, safe_messages, temperature, max_tokens)
        if used and self.org_id is not None:
            await _record_llm_usage(used, self.org_id, self.meeting_id, self.user_id)
        return p.restore(answer)


async def _record_llm_usage(
    used: list[tuple[str, str, int, int]],
    org_id: uuid.UUID,
    meeting_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
) -> None:
    """Tokens de una llamada a la IA. Anotarlos nunca corta la respuesta."""
    from ..db import SessionLocal
    from .plans import llm_cost, record_usage

    try:
        async with SessionLocal() as db:
            for provider, model, tokens_in, tokens_out in used:
                cost = llm_cost(model, tokens_in, tokens_out)
                await record_usage(
                    db, kind="llm", provider=provider, model=model, unit="tokens",
                    quantity=tokens_in + tokens_out, cost_usd=cost or 0.0,
                    organization_id=org_id, user_id=user_id, meeting_id=meeting_id,
                    meta={"tokens_in": tokens_in, "tokens_out": tokens_out, **({} if cost is not None else {"price_unknown": True})},
                )
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("no se pudo anotar el consumo del LLM: %s", exc)


# ── armado desde la base ─────────────────────────────────────────

_CACHE_SECONDS = 120
_org_cache: dict[uuid.UUID, tuple[float, list[Person]]] = {}

# Etiquetas de hablante que no son nombres.
_GENERIC_SPEAKER = re.compile(r"(speaker|hablante|persona|participante|\d)", re.IGNORECASE)


async def _org_people(db: AsyncSession, org_id: uuid.UUID) -> list[Person]:
    cached = _org_cache.get(org_id)
    if cached and time.monotonic() - cached[0] < _CACHE_SECONDS:
        return cached[1]
    from ..models import (
        Family, FamilyMember, OrganizationMember, OrgProtectedName, Professional, User,
    )

    people: list[Person] = []

    def add(name, kind, group=None, extra=None):
        person = Person.parse(name, kind, group, extra)
        if person:
            people.append(person)

    for (name,) in (await db.execute(
        select(User.name).join(OrganizationMember, OrganizationMember.user_id == User.id)
        .where(OrganizationMember.organization_id == org_id)
    )).all():
        add(name, "personal")
    for (name,) in (await db.execute(
        select(Professional.name).where(Professional.organization_id == org_id)
    )).all():
        add(name, "profesional")
    for name, relationship, family_id in (await db.execute(
        select(FamilyMember.name, FamilyMember.relationship_type, FamilyMember.family_id)
        .join(Family, Family.id == FamilyMember.family_id)
        .where(Family.organization_id == org_id, Family.deleted_at.is_(None))
    )).all():
        add(name, relationship, f"family:{family_id}")
    for row in (await db.execute(
        select(OrgProtectedName).where(OrgProtectedName.organization_id == org_id)
    )).scalars():
        add(row.name, row.kind, row.group_key, row.extra)

    _org_cache[org_id] = (time.monotonic(), people)
    return people


def forget_org_cache(org_id: uuid.UUID) -> None:
    _org_cache.pop(org_id, None)


# Tipos de entidad de ElevenLabs Scribe que son nombres de persona (en la
# reunión del 27/9 devolvió "name", "name_given" y "name_family").
_NAME_ENTITY = re.compile(r"^(person|name)", re.IGNORECASE)


# Entidades de Scribe que NO son datos personales: números dichos ("uno, dos,
# tres"), "profe", fechas de un compromiso. Todo lo demás de pii/phi
# (dirección, teléfono, documento, diagnóstico, medicación) se tapa.
_HARMLESS_ENTITY = re.compile(
    r"^(cardinal|ordinal|occupation|language|date|time|duration|quantity|percent|money)$", re.IGNORECASE
)


def detected_data(meta: dict | None) -> list[str]:
    """Datos personales o de salud que Scribe detectó (meta.detected_entities)."""
    out: list[str] = []
    for entity in (meta or {}).get("detected_entities") or []:
        text = " ".join(str(entity.get("text") or "").split())
        kind = str(entity.get("type") or "")
        if text and kind and not _NAME_ENTITY.match(kind) and not _HARMLESS_ENTITY.match(kind) and text not in out:
            out.append(text)
    return out


def detected_names(meta: dict | None) -> list[str]:
    """Nombres que Scribe detectó en el audio (meta.detected_entities).

    Un nombre de pila o apellido suelto que ya es parte de un nombre completo
    detectado no se agrega aparte: "Bautista" y "Goñi" son "Bautista Goñi",
    no dos personas más.
    """
    names: list[str] = []
    for entity in (meta or {}).get("detected_entities") or []:
        text = " ".join(str(entity.get("text") or "").split())
        if text and _NAME_ENTITY.match(str(entity.get("type") or "")) and text not in names:
            names.append(text)
    full = [set(fold(name).split()) for name in names if len(name.split()) > 1]
    return [
        name for name in names
        if len(name.split()) > 1 or not any(fold(name) in words for words in full)
    ]


async def build_pseudonymizer(
    db: AsyncSession, org_id: uuid.UUID, meeting_id: uuid.UUID | None = None
) -> Pseudonymizer:
    from ..models import Meeting, MeetingParticipant, Speaker

    from ..models import Organization

    people = await _org_people(db, org_id)
    organization = await db.get(Organization, org_id)
    keep = set(_WORD.findall(organization.name)) if organization is not None and organization.name else set()
    priority_people: list[Person] = []
    priority_groups: set[str] = set()
    data: list[str] = []
    if meeting_id:
        meeting = await db.get(Meeting, meeting_id)
        if meeting is not None and meeting.family_id:
            priority_groups.add(f"family:{meeting.family_id}")
        data = detected_data(meeting.meta if meeting is not None else None)
        # Lo que se dijo en voz alta aunque no esté en ninguna nómina: los
        # nombres que detectó la pasada final (services/diarization.py).
        for name in detected_names(meeting.meta if meeting is not None else None):
            person = Person.parse(name, "persona")
            if person:
                priority_people.append(person)
        for (name,) in (await db.execute(
            select(MeetingParticipant.name).where(MeetingParticipant.meeting_id == meeting_id)
        )).all():
            person = Person.parse(name, "persona")
            if person:
                priority_people.append(person)
        for (name,) in (await db.execute(
            select(Speaker.display_name).where(Speaker.meeting_id == meeting_id, Speaker.display_name.is_not(None))
        )).all():
            if name and not _GENERIC_SPEAKER.search(name) and fold(name) not in STOPWORDS:
                person = Person.parse(name, "persona")
                if person:
                    priority_people.append(person)
    return Pseudonymizer(people, priority_groups, priority_people, data, keep)


async def protect(
    db: AsyncSession,
    org_id: uuid.UUID,
    provider: LLMProvider,
    meeting_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> LLMProvider:
    """El provider que tienen que usar todos: nunca manda nombres afuera.

    `user_id` es a quién se le cuenta el consumo (quien pregunta en el chat,
    quien grabó la reunión en el acta).
    """
    return PrivateLLMProvider(
        provider, await build_pseudonymizer(db, org_id, meeting_id), org_id, meeting_id, user_id
    )


async def scrub_for_embeddings(
    db: AsyncSession, org_id: uuid.UUID, texts: list[str], meeting_id: uuid.UUID | None = None
) -> list[str]:
    """Para embeddings no hace falta restaurar: basta con que el nombre no salga.

    El marcador lleva solo el tipo ("[ALUMNO]") para que el mismo nombre dé
    el mismo vector en todas las reuniones.
    """
    pseudo = await build_pseudonymizer(db, org_id, meeting_id)
    out = []
    for text in texts:
        scrubbed = pseudo.apply(text)
        out.append(re.sub(r"\[([A-Z]+)_\d+\]", r"[\1]", scrubbed))
    return out
