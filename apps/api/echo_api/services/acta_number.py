"""Numeración de actas: correlativa por organización (la sede) y serie.

Reglas:
- Un acta recibe su número una sola vez, lo primero que pase entre que se
  genera y que se imprime. Regenerarla o reimprimirla no le cambia el número.
- Dos actas nunca comparten número. El contador se toma con un bloqueo de
  fila, así que dos personas que imprimen a la vez reciben 1 y 2, no 1 y 1.
  El índice único uq_minutes_number es la red de seguridad por si el
  contador se configurara mal.
- El número inicial se configura (para seguir la numeración del sistema
  anterior al mudarse a Echo), pero nunca por debajo de uno ya usado.

Hoy hay una sola serie, "general". La columna existe para que más adelante
cada nivel (o secundaria por motivo) tenga su propia numeración sin migrar.
"""
import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Minutes, MinutesCounter

SERIES_GENERAL = "general"


async def _locked_counter(db: AsyncSession, org_id: uuid.UUID, series: str) -> MinutesCounter:
    """Devuelve el contador de la serie bloqueado hasta el commit.

    Si no existe lo crea arrancando en 1; ON CONFLICT cubre el caso de dos
    transacciones que lo crean a la vez.
    """
    await db.execute(
        pg_insert(MinutesCounter)
        .values(id=uuid.uuid4(), organization_id=org_id, series=series, next_number=1)
        .on_conflict_do_nothing(constraint="uq_minutes_counter_series")
    )
    return (
        await db.execute(
            select(MinutesCounter)
            .where(MinutesCounter.organization_id == org_id, MinutesCounter.series == series)
            .with_for_update()
            # Sin esto, si el contador ya estaba en la sesión, SQLAlchemy
            # devolvería el valor viejo en memoria y no el recién bloqueado.
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def ensure_number(db: AsyncSession, minutes_id: uuid.UUID) -> int:
    """Asigna número al acta si todavía no tiene y lo devuelve. No hace commit.

    Bloquea primero el acta y después el contador, siempre en ese orden, para
    que dos pedidos sobre la misma acta no le asignen dos números.
    """
    minutes = (
        await db.execute(
            select(Minutes)
            .where(Minutes.id == minutes_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    if minutes.number is not None:
        return minutes.number

    counter = await _locked_counter(db, minutes.organization_id, SERIES_GENERAL)
    number = counter.next_number
    counter.next_number = number + 1
    minutes.number = number
    minutes.number_series = SERIES_GENERAL
    await db.flush()
    return number


async def last_assigned(db: AsyncSession, org_id: uuid.UUID, series: str = SERIES_GENERAL) -> int | None:
    return (
        await db.execute(
            select(func.max(Minutes.number)).where(
                Minutes.organization_id == org_id, Minutes.number_series == series
            )
        )
    ).scalar_one()


async def get_next_number(db: AsyncSession, org_id: uuid.UUID, series: str = SERIES_GENERAL) -> int:
    counter = (
        await db.execute(
            select(MinutesCounter).where(
                MinutesCounter.organization_id == org_id, MinutesCounter.series == series
            )
        )
    ).scalar_one_or_none()
    if counter is not None:
        return counter.next_number
    # Sin contador todavía: el próximo es el siguiente al último usado.
    return (await last_assigned(db, org_id, series) or 0) + 1


class NumberTooLow(ValueError):
    """El número pedido ya fue usado (o es menor a uno usado)."""

    def __init__(self, minimum: int):
        super().__init__(f"El próximo número tiene que ser {minimum} o más: hasta el {minimum - 1} ya se usaron.")
        self.minimum = minimum


async def set_next_number(
    db: AsyncSession, org_id: uuid.UUID, next_number: int, series: str = SERIES_GENERAL
) -> int:
    """Fija el próximo número de la serie. No hace commit.

    Se valida con el contador bloqueado: si en el medio alguien imprimió, el
    mínimo ya lo contempla.
    """
    counter = await _locked_counter(db, org_id, series)
    minimum = (await last_assigned(db, org_id, series) or 0) + 1
    if next_number < minimum:
        raise NumberTooLow(minimum)
    counter.next_number = next_number
    await db.flush()
    return next_number
