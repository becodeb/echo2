"""Fixtures de la suite de Echo API.

Los tests corren contra una base PostgreSQL real (echo_test) para probar
pgvector, tsvector y aislamiento de tenant de verdad. Ejecutar con:

    docker compose exec api pytest

El schema de la base de test lo arma `alembic upgrade head` sobre una base
recién creada y vacía, NO Base.metadata.create_all(). Es a propósito: correr
la cadena de migraciones en cada suite es lo único que detecta una migración
que explota en una base nueva, que es exactamente lo que se escapó a
producción como un 502 (commit 818b3dc). Si esto se vuelve a cambiar por un
create_all(), ese agujero vuelve a abrirse.

Los providers externos (LLM/STT/embeddings) se reemplazan por fakes DE TEST
que implementan las mismas interfaces — nunca llegan a producción.
"""
import asyncio
import json
import os
import uuid
from pathlib import Path

# Configurar la base de test ANTES de importar echo_api
_default = os.environ.get("DATABASE_URL", "postgresql+asyncpg://echo:echo_dev_pw@db:5432/echo")
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", _default.rsplit("/", 1)[0] + "/echo_test"
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["ECHO_ENV"] = "test"

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Raíz de apps/api: alembic.ini y el directorio alembic/ cuelgan de acá.
API_ROOT = Path(__file__).resolve().parents[1]


def _admin_url() -> str:
    return TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"


async def _recreate_empty_database() -> None:
    """Borra y vuelve a crear la base de test, vacía del todo.

    Se recrea en vez de limpiar tablas para que las migraciones se apliquen
    siempre sobre una base nueva de verdad, que es el caso que rompió en
    producción. WITH (FORCE) corta las conexiones que hayan quedado colgadas
    de una corrida anterior (necesita PostgreSQL 13+; la imagen es pg17).
    """
    database_name = TEST_DATABASE_URL.rsplit("/", 1)[1]
    admin = create_async_engine(_admin_url(), isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        await connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'))
        await connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    await admin.dispose()


def _run_migrations() -> None:
    """Aplica `alembic upgrade head` contra la base de test recién creada.

    env.py toma la URL de DATABASE_URL, que arriba ya apunta a echo_test.
    La extensión pgvector la crea la migración 0001: a propósito NO se crea
    acá, así una migración que se olvide de la extensión falla en los tests
    en vez de fallar en el deploy.

    El Config se arma a mano en vez de leer alembic.ini: env.py llama a
    fileConfig() cuando hay archivo de config, y eso desactiva los loggers ya
    existentes, con lo cual caplog deja de ver los warnings de la app y los
    tests que los verifican fallan. Sin archivo, config_file_name es None,
    env.py saltea fileConfig() y el logging de pytest queda intacto. Lo único
    que alembic.ini aporta además del logging es script_location, que se fija
    acá abajo en absoluto porque los tests no siempre corren con cwd en
    apps/api.
    """
    from alembic import command
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    config.set_main_option("prepend_sys_path", str(API_ROOT))
    command.upgrade(config, "head")


@pytest.fixture(scope="session", autouse=True)
def prepare_database():
    asyncio.run(_recreate_empty_database())
    _run_migrations()
    yield


@pytest.fixture()
def client(prepare_database):
    from starlette.testclient import TestClient

    from echo_api.main import app

    with TestClient(app) as test_client:
        yield test_client


class EchoTestUser:
    """Helper: usuario registrado con organización y headers listos."""

    def __init__(self, client, name: str = "Ana Tester", org_name: str = "Org Test"):
        self.client = client
        self.email = f"user-{uuid.uuid4().hex[:10]}@test.echo"
        self.password = "supersegura123"
        response = client.post(
            "/api/auth/register",
            json={"email": self.email, "password": self.password, "name": name},
        )
        assert response.status_code == 201, response.text
        session = response.json()
        self.user_id = session["user"]["id"]
        self.token = session["access_token"]
        org_response = client.post(
            "/api/auth/organizations",
            json={"name": org_name},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        assert org_response.status_code == 201, org_response.text
        self.org_id = org_response.json()["id"]

    @property
    def headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "X-Organization-Id": self.org_id,
        }


@pytest.fixture()
def user(client) -> EchoTestUser:
    return EchoTestUser(client)


# ── Fakes de IA (solo tests) ─────────────────────────────────────


class SmartFakeLLM:
    """LLM fake que responde JSON coherente según el prompt recibido."""

    name = "fake"
    model = "fake-model"

    def __init__(self):
        self.calls: list[dict] = []

    async def chat(self, system, messages, temperature=0.2, max_tokens=4096) -> str:
        self.calls.append({"system": system, "user": messages[-1]["content"] if messages else ""})
        prompt = (messages[-1]["content"] if messages else "") + system

        if "análisis post-reunión" in system or "post-reunión" in system:
            return json.dumps(
                {
                    "topics": [{"title": "Presupuesto", "summary": "Se habló del presupuesto", "start_ms": 0, "end_ms": 9000}],
                    "decisions": [
                        {"text": "El lanzamiento se mueve al viernes", "context": "retraso del proveedor",
                         "evidence_start_ms": 4000, "evidence_end_ms": 6000}
                    ],
                    "tasks": [
                        {"text": "Pedir tres presupuestos", "assignee": "Marcos", "due": "viernes",
                         "evidence_start_ms": 2000, "evidence_end_ms": 4000}
                    ],
                    "questions": [{"text": "¿Cuánto cuesta la licencia anual?", "evidence_start_ms": 6000, "evidence_end_ms": 7000}],
                    "risks": [{"text": "El proveedor puede retrasar la entrega", "evidence_start_ms": 5000, "evidence_end_ms": 6000}],
                    "mentions": {"people": ["Marcos", "Ana"], "projects": ["DOE"], "dates": [], "numbers": [], "links": []},
                    "timeline": [{"at_ms": 0, "label": "Inicio"}, {"at_ms": 4000, "label": "Decisión de fecha"}],
                    "next_steps": ["Confirmar presupuesto"],
                }
            )
        if "redactor de resúmenes" in system:
            return json.dumps(
                {
                    "executive": ["Se decidió mover el lanzamiento al viernes", "Marcos pedirá presupuestos"],
                    "detailed": "## Resumen\nLa reunión trató el presupuesto y la fecha de lanzamiento.",
                }
            )
        if "generador de actas" in system:
            return json.dumps(
                {
                    "markdown": "# ACTA DE REUNIÓN\n\n## Decisiones adoptadas\n- El lanzamiento se mueve al viernes\n\n## Compromisos y tareas\n| Tarea | Responsable | Fecha límite |\n|---|---|---|\n| Pedir tres presupuestos | Marcos | viernes |\n",
                    "claims": [
                        {"text": "El lanzamiento se mueve al viernes", "approx_ms": 4000},
                        {"text": "Marcos pedirá tres presupuestos", "approx_ms": 2000},
                    ],
                }
            )
        if "verificador" in system:
            return json.dumps({"status": "verified", "evidence_ms": 4000, "note": "ok"})
        if "motor de análisis" in system:  # live extract
            return json.dumps({"decisions": [], "tasks": [], "questions": []})
        if "memoria de reuniones" in system or "asistente de reuniones" in system:
            # chat: responder citando el contexto recibido
            return "Se decidió mover el lanzamiento al viernes [00:04]."
        return "{}"

    async def chat_json(self, system, messages, temperature=0.1, max_tokens=4096):
        from echo_api.services.llm.base import parse_json_loose

        return parse_json_loose(await self.chat(system, messages, temperature, max_tokens))


@pytest.fixture()
def fake_ai(monkeypatch):
    """Parchea toda la resolución de IA hacia fakes de test."""
    from echo_api.services.ai_settings import EmbeddingsConfig, LLMConfig, SttConfig

    fake_llm = SmartFakeLLM()
    llm_config = LLMConfig(provider="fake", model="fake-model", api_key="x")
    stt_config = SttConfig(provider="fake", model=None, api_key="x")
    embeddings_config = EmbeddingsConfig(provider="fake", model="fake-embed", api_key="x")

    async def fake_resolve_llm(db, org_id):
        return llm_config

    async def fake_resolve_stt(db, org_id):
        return stt_config

    async def fake_resolve_embeddings(db, org_id):
        return embeddings_config

    def fake_get_llm_provider(provider, api_key, model, base_url=None):
        return fake_llm

    import echo_api.routers.chat as chat_module
    import echo_api.routers.minutes as minutes_module
    import echo_api.services.insights_live as insights_live_module
    import echo_api.services.memory_svc as memory_module
    import echo_api.services.minutes_gen as minutes_gen_module
    import echo_api.services.pipeline as pipeline_module

    for module in (pipeline_module, insights_live_module, chat_module, minutes_module):
        if hasattr(module, "resolve_llm"):
            monkeypatch.setattr(module, "resolve_llm", fake_resolve_llm)
        if hasattr(module, "get_llm_provider"):
            monkeypatch.setattr(module, "get_llm_provider", fake_get_llm_provider)
    monkeypatch.setattr(pipeline_module, "resolve_embeddings", fake_resolve_embeddings)
    import echo_api.routers.search as search_module

    monkeypatch.setattr(chat_module, "resolve_embeddings", fake_resolve_embeddings)
    monkeypatch.setattr(search_module, "resolve_embeddings", fake_resolve_embeddings)

    return fake_llm
