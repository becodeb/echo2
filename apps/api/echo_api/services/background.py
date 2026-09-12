"""Tareas de fondo que sobreviven al garbage collector.

`asyncio.create_task` devuelve la ÚNICA referencia fuerte a la tarea: el event
loop guarda apenas una débil. Si el llamador tira ese valor, el recolector
puede llevarse la tarea a mitad de ejecución, y lo que desaparece no es un
detalle: la transcripción de un audio importado (minutos de trabajo) o el
pipeline post-reunión entero de un dispositivo.

Acá las retenemos hasta que terminan y de paso las miramos al final. Una tarea
de fondo que revienta en silencio es una falla que no existe para nadie: no
hay nadie esperando el resultado que se entere del error.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

log = logging.getLogger("echo.background")

# Referencias fuertes vivas mientras la tarea corre. Set y no lista porque el
# descarte es por identidad y tiene que ser O(1): acá pasa cada chunk de
# insights en vivo, no sólo los trabajos largos.
_running: set[asyncio.Task[Any]] = set()


def spawn(coro: Coroutine[Any, Any, Any], *, name: str | None = None) -> asyncio.Task[Any]:
    """Lanza `coro` en segundo plano reteniendo la tarea hasta que termine.

    Reemplaza a `asyncio.create_task` en todo lugar donde el resultado no se
    espera. `name` sale en el log si la tarea muere con error, así que conviene
    que diga qué reunión era.
    """
    task = asyncio.create_task(coro, name=name)
    _running.add(task)
    task.add_done_callback(_on_done)
    return task


def _on_done(task: asyncio.Task[Any]) -> None:
    _running.discard(task)
    if task.cancelled():
        # Cancelar es una decisión nuestra (apagado, WebSocket cerrado): no es
        # una falla y no ensucia el log.
        return
    error = task.exception()
    if error is not None:
        log.error(
            "tarea de fondo %s terminó con error: %s", task.get_name(), error, exc_info=error
        )


def pending_count() -> int:
    """Cuántas tareas hay retenidas ahora mismo. Existe para los tests."""
    return len(_running)
