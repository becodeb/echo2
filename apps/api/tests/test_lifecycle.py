"""Regresiones del ciclo de vida de recursos.

Tres fallas que no rompían ningún test porque ninguna deja excepción: el
import leía el archivo entero a RAM antes de validarlo (muere el proceso, no
la request), las tareas de fondo se podían perder por el garbage collector, y
los estados "generating"/"processing" no tenían quién los cerrara si la API se
reiniciaba en el medio.

Cada test de acá está escrito para fallar si se revierte el arreglo, no para
confirmar que el código actual hace lo que hace.
"""
import asyncio
import gc
import logging
import os
import tempfile
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from conftest import EchoTestUser


# ── Bloqueante 4: el import no puede materializar el archivo entero ──


class _FakeUpload:
    """UploadFile de mentira que mide cuánto se leyó DE VERDAD.

    El punto del test no es el código de estado: es que el servidor nunca
    llegue a tener el archivo completo. Por eso este fake cuenta los bytes
    servidos y el tamaño de la lectura más grande que le pidieron.
    """

    def __init__(self, total_bytes: int, filename: str = "grande.mp3"):
        self.filename = filename
        self._left = total_bytes
        self.served = 0
        self.biggest_read = 0

    async def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            # Así se comportaba el código viejo: pedir todo de una. Si alguien
            # lo reintroduce, el contador de abajo lo delata.
            size = self._left
        self.biggest_read = max(self.biggest_read, size)
        take = min(size, self._left)
        self._left -= take
        self.served += take
        return b"\0" * take


def test_import_rechaza_el_sobredimensionado_sin_leerlo_entero():
    from fastapi import HTTPException

    from echo_api.routers.imports import UPLOAD_CHUNK_BYTES, _spool_upload

    max_bytes = 3 * UPLOAD_CHUNK_BYTES
    upload = _FakeUpload(total_bytes=64 * UPLOAD_CHUNK_BYTES)  # 64 MiB "subidos"
    antes = set(os.listdir(tempfile.gettempdir()))

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(_spool_upload(upload, ".mp3", max_bytes))

    assert excinfo.value.status_code == 413
    # Nunca pidió más de un chunk de una sentada.
    assert upload.biggest_read <= UPLOAD_CHUNK_BYTES
    # Y cortó apenas pasó el límite, en vez de consumir los 64 MiB.
    assert upload.served <= max_bytes + UPLOAD_CHUNK_BYTES
    # PRIVACY: el upload rechazado no deja restos en disco.
    nuevos = set(os.listdir(tempfile.gettempdir())) - antes
    assert not [n for n in nuevos if n.endswith(".mp3")]


def test_import_acepta_el_que_entra_y_deja_la_ruta_no_los_bytes():
    """Contraprueba: dentro del límite el archivo se vuelca completo a disco."""
    from echo_api.routers.imports import UPLOAD_CHUNK_BYTES, _remove, _spool_upload

    tamanio = UPLOAD_CHUNK_BYTES * 2 + 123
    upload = _FakeUpload(total_bytes=tamanio)
    path, total = asyncio.run(_spool_upload(upload, ".mp3", max_bytes=10 * UPLOAD_CHUNK_BYTES))
    try:
        assert total == tamanio
        assert os.path.getsize(path) == tamanio
    finally:
        _remove(path)
    assert not os.path.exists(path)


def test_import_corta_por_content_length_antes_de_leer(client, monkeypatch):
    """El atajo del header: 413 sin tocar el cuerpo.

    Es un atajo y no la defensa: el header lo escribe el cliente. La defensa
    real la cubre el test de _spool_upload de arriba.
    """
    from echo_api.config import get_settings
    import echo_api.routers.imports as imports_module
    from echo_api.services.ai_settings import SttConfig

    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)

    async def fake_resolve_stt(db, org_id):
        return SttConfig(provider="fake", model=None, api_key="x")

    monkeypatch.setattr(imports_module, "resolve_stt", fake_resolve_stt)

    user = EchoTestUser(client, name="Importa", org_name="Org Import")
    meeting_id = client.post(
        "/api/meetings", json={"title": "Audio grande"}, headers=user.headers
    ).json()["id"]

    response = client.post(
        f"/api/meetings/{meeting_id}/import",
        files={"file": ("grande.mp3", b"\0" * (2 * 1024 * 1024), "audio/mpeg")},
        headers=user.headers,
    )
    assert response.status_code == 413
    assert "1 MB" in response.json()["detail"]
    # La reunión no puede haber quedado marcada como en proceso por un upload
    # que se rechazó.
    meeting = client.get(f"/api/meetings/{meeting_id}", headers=user.headers).json()
    assert meeting["status"] == "draft"


# ── Bloqueante 5: las tareas de fondo tienen que sobrevivir al GC ──


def test_spawn_retiene_la_tarea_y_loguea_su_error(caplog):
    from echo_api.services import background

    async def escenario():
        arranco = asyncio.Event()

        async def falla():
            arranco.set()
            await asyncio.sleep(0)
            raise RuntimeError("se cayó el proveedor")

        task = background.spawn(falla(), name="tarea-de-prueba")
        assert background.pending_count() == 1

        # Lo que rompía antes: el llamador suelta la única referencia fuerte.
        # Acá el set del módulo la sostiene igual.
        del task
        gc.collect()
        assert background.pending_count() == 1

        await arranco.wait()
        for _ in range(50):
            await asyncio.sleep(0.01)
            if background.pending_count() == 0:
                break
        # Terminada, se descarta sola: el set no crece para siempre.
        assert background.pending_count() == 0

    with caplog.at_level(logging.ERROR, logger="echo.background"):
        asyncio.run(escenario())

    # Y la falla dejó rastro: antes moría en absoluto silencio.
    assert "tarea-de-prueba" in caplog.text
    assert "se cayó el proveedor" in caplog.text


def test_spawn_no_ensucia_el_log_cuando_la_tarea_sale_bien(caplog):
    """Contraprueba: sin error no hay log de error."""
    from echo_api.services import background

    async def escenario():
        async def ok():
            return 42

        task = background.spawn(ok(), name="tarea-sana")
        assert await task == 42
        await asyncio.sleep(0)
        assert background.pending_count() == 0

    with caplog.at_level(logging.ERROR, logger="echo.background"):
        asyncio.run(escenario())
    assert "tarea-sana" not in caplog.text


# ── Bloqueante 6: el watchdog cierra lo vencido y sólo lo vencido ──


def _sql(statements: list[tuple[str, dict]]) -> None:
    async def go():
        from echo_api.db import SessionLocal

        async with SessionLocal() as db:
            for statement, params in statements:
                await db.execute(text(statement), params)
            await db.commit()

    asyncio.run(go())


def _fetch(statement: str, params: dict) -> dict:
    async def go():
        from echo_api.db import SessionLocal

        async with SessionLocal() as db:
            row = (await db.execute(text(statement), params)).mappings().first()
            return dict(row) if row else {}

    return asyncio.run(go())


def _preparar_trabajo(client, user, titulo: str, edad: timedelta) -> tuple[str, str]:
    """Crea una reunión en 'processing' y su acta en 'generating', envejecidas."""
    meeting_id = client.post(
        "/api/meetings", json={"title": titulo}, headers=user.headers
    ).json()["id"]
    minutes_id = str(uuid.uuid4())
    momento = datetime.now(UTC) - edad
    _sql(
        [
            (
                "UPDATE meetings SET status = 'processing', processing_state = '{}'::jsonb, "
                "updated_at = :momento WHERE id = :mid",
                {"momento": momento, "mid": meeting_id},
            ),
            (
                "INSERT INTO minutes (id, meeting_id, organization_id, status, current_version, "
                "generation_status, generation_started_at, created_at, updated_at) "
                "VALUES (:id, :mid, :org, 'draft', 0, 'generating', :momento, now(), now())",
                {
                    "id": minutes_id,
                    "mid": meeting_id,
                    "org": user.org_id,
                    "momento": momento,
                },
            ),
        ]
    )
    return meeting_id, minutes_id


def test_watchdog_cierra_lo_vencido_y_respeta_lo_que_sigue_a_tiempo(client):
    from echo_api.main import STALE_JOB_HOURS, _fail_stale_jobs

    user = EchoTestUser(client, name="Watchdog", org_name="Org Watchdog")
    # Uno claramente vencido y otro recién arrancado. La contraprueba es la que
    # importa: sin ella el test pasaría aunque el watchdog fallara TODO.
    viejo_meeting, viejo_minutes = _preparar_trabajo(
        client, user, "Colgada", timedelta(hours=STALE_JOB_HOURS + 1)
    )
    fresco_meeting, fresco_minutes = _preparar_trabajo(
        client, user, "En curso", timedelta(minutes=5)
    )

    asyncio.run(_fail_stale_jobs())

    vencida = _fetch("SELECT status, processing_state FROM meetings WHERE id = :id",
                     {"id": viejo_meeting})
    assert vencida["status"] == "failed"
    assert vencida["processing_state"]["stage"] == "failed"

    acta_vencida = _fetch(
        "SELECT generation_status, generation_error FROM minutes WHERE id = :id",
        {"id": viejo_minutes},
    )
    assert acta_vencida["generation_status"] == "failed"
    # El mensaje es para una persona, no un código: tiene que decir qué hacer.
    assert "Regenerar" in acta_vencida["generation_error"]

    # Contraprueba: el trabajo que puede seguir vivo en otra instancia queda intacto.
    en_curso = _fetch("SELECT status FROM meetings WHERE id = :id", {"id": fresco_meeting})
    assert en_curso["status"] == "processing"
    acta_en_curso = _fetch(
        "SELECT generation_status, generation_error FROM minutes WHERE id = :id",
        {"id": fresco_minutes},
    )
    assert acta_en_curso["generation_status"] == "generating"
    assert acta_en_curso["generation_error"] is None
