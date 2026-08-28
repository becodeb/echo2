"""Resolución de fechas relativas en español/inglés/portugués.

"viernes" + fecha real de la reunión → 2026-08-28. Guardamos SIEMPRE el texto
original y, si se puede, la fecha resuelta. Sin dependencias externas.
"""
import re
import unicodedata
from datetime import date, timedelta

WEEKDAYS = {
    # español
    "lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4, "sabado": 5, "domingo": 6,
    # inglés
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
    # portugués
    "segunda": 0, "terca": 1, "quarta": 2, "quinta": 3, "sexta": 4,
}

MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "janeiro": 1, "fevereiro": 2, "marco": 3, "maio": 5, "junho": 6,
    "julho": 7, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}


def _strip_accents(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    )


def resolve_relative_date(text: str | None, reference: date) -> date | None:
    """Intenta resolver una expresión de fecha relativa a la fecha de la reunión."""
    if not text:
        return None
    normalized = _strip_accents(text.strip().lower())

    if normalized in ("hoy", "today", "hoje"):
        return reference
    if normalized in ("manana", "tomorrow", "amanha"):
        return reference + timedelta(days=1)
    if normalized in ("pasado manana",):
        return reference + timedelta(days=2)

    # "el viernes", "next friday", "viernes que viene", "este viernes"
    weekday_match = re.search(
        r"(?:proximo|proxima|next|este|esta|el|la|na|no)?\s*"
        r"(lunes|martes|miercoles|jueves|viernes|sabado|domingo|"
        r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
        r"segunda|terca|quarta|quinta|sexta)(?:\s*(?:que viene|proximo|feira))?",
        normalized,
    )
    if weekday_match:
        target = WEEKDAYS[weekday_match.group(1)]
        delta = (target - reference.weekday()) % 7
        if delta == 0:
            delta = 7  # "el viernes" dicho un viernes = el próximo
        return reference + timedelta(days=delta)

    # "en 2 semanas", "in 3 days", "en 10 dias"
    span_match = re.search(r"(?:en|in|em)\s+(\d{1,3})\s+(dia|dias|day|days|semana|semanas|week|weeks|mes|meses|month|months)", normalized)
    if span_match:
        amount = int(span_match.group(1))
        unit = span_match.group(2)
        if unit.startswith(("dia", "day")):
            return reference + timedelta(days=amount)
        if unit.startswith(("semana", "week")):
            return reference + timedelta(weeks=amount)
        return _add_months(reference, amount)

    if "fin de mes" in normalized or "end of month" in normalized:
        next_month = _add_months(reference.replace(day=1), 1)
        return next_month - timedelta(days=1)
    if "fin de semana" in normalized:
        delta = (5 - reference.weekday()) % 7
        return reference + timedelta(days=delta or 7)
    if "proxima semana" in normalized or "next week" in normalized or "semana que viene" in normalized:
        return reference + timedelta(days=(7 - reference.weekday()))

    # "15 de septiembre", "el 15/9", "15/09/2026", "september 15"
    dm = re.search(r"(\d{1,2})\s*(?:de\s+)?([a-z]+)(?:\s+(?:de\s+)?(\d{4}))?", normalized)
    if dm and dm.group(2) in MONTHS:
        day = int(dm.group(1))
        month = MONTHS[dm.group(2)]
        year = int(dm.group(3)) if dm.group(3) else reference.year
        try:
            resolved = date(year, month, day)
        except ValueError:
            return None
        if not dm.group(3) and resolved < reference:
            resolved = date(year + 1, month, day)
        return resolved

    md = re.search(r"([a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(\d{4}))?", normalized)
    if md and md.group(1) in MONTHS:
        month = MONTHS[md.group(1)]
        day = int(md.group(2))
        year = int(md.group(3)) if md.group(3) else reference.year
        try:
            resolved = date(year, month, day)
        except ValueError:
            return None
        if not md.group(3) and resolved < reference:
            resolved = date(year + 1, month, day)
        return resolved

    iso = re.search(r"(\d{4})-(\d{2})-(\d{2})", normalized)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            return None

    slash = re.search(r"(\d{1,2})[/\-](\d{1,2})(?:[/\-](\d{2,4}))?", normalized)
    if slash:
        day, month = int(slash.group(1)), int(slash.group(2))
        year = reference.year
        if slash.group(3):
            year = int(slash.group(3))
            if year < 100:
                year += 2000
        try:
            resolved = date(year, month, day)
        except ValueError:
            return None
        if not slash.group(3) and resolved < reference:
            resolved = _add_months(resolved, 12)
        return resolved

    return None


def _add_months(base: date, months: int) -> date:
    month_index = base.month - 1 + months
    year = base.year + month_index // 12
    month = month_index % 12 + 1
    day = min(base.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)
