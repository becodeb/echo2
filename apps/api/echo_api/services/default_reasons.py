"""Motivos de reunión con los que arranca cada organización.

Son los habituales de un colegio. Se cargan al crear la organización para que
el desplegable no arranque vacío; después cada colegio los edita, desactiva o
agrega los suyos en Ajustes → Motivos de reunión.

La migración 0010 tiene su propia copia de esta lista (una migración no debe
depender del código de la app); si se cambia acá, no hace falta tocarla.
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import MeetingReason

DEFAULT_REASONS = [
    "Desempeño académico",
    "Conducta",
    "Convivencia escolar",
    "Asistencia e inasistencias",
    "Dificultades de aprendizaje",
    "Aspectos socioemocionales",
    "Vínculo con compañeros",
    "Situación familiar",
    "Salud",
    "Inclusión y acompañamiento (PPI)",
    "Situación de acoso escolar",
    "Devolución de informes",
    "Entrevista de ingreso",
    "Orientación vocacional",
    "Seguimiento",
    "Otro",
]


def add_default_reasons(db: AsyncSession, org_id: uuid.UUID) -> None:
    for position, name in enumerate(DEFAULT_REASONS, start=1):
        db.add(MeetingReason(organization_id=org_id, name=name, is_active=True, position=position))
