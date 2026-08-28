"""Fixtures de la suite de Echo API.

Los tests corren contra una base PostgreSQL real (echo_test) para probar
pgvector, tsvector y aislamiento de tenant de verdad. Ejecutar con:

    docker compose exec api pytest

Los providers externos (LLM/STT/embeddings) se reemplazan por fakes DE TEST
que implementan las mismas interfaces — nunca llegan a producción.
"""
import asyncio
import json
import os
import uuid

# Configurar la base de test ANTES de importar echo_api
_default = os.environ.get("DATABASE_URL", "postgresql+asyncpg://echo:echo_dev_pw@db:5432/echo")
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", _default.rsplit("/", 1)[0] + "/echo_test"
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["ECHO_ENV"] = "test"

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from echo_api.models import Base  # noqa: E402


def _admin_url() -> str:
    return TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"


async def _prepare_database() -> None:
    admin = create_async_engine(_admin_url(), isolation_level="AUTOCOMMIT")
    database_name = TEST_DATABASE_URL.rsplit("/", 1)[1]
    async with admin.connect() as connection:
        from sqlalchemy import text

        exists = await connection.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": database_name}
        )
        if not exists.scalar():
            await connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    await admin.dispose()

    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as connection:
        from sqlalchemy import text

        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(
            text(
                """
                CREATE OR REPLACE FUNCTION transcript_segments_tsv_update() RETURNS trigger AS $$
                BEGIN
                    NEW.tsv := to_tsvector('spanish', coalesce(NEW.text, ''));
                    RETURN NEW;
                END
                $$ LANGUAGE plpgsql;
                """
            )
        )
        await connection.execute(
            text(
                """
                CREATE TRIGGER trg_transcript_segments_tsv
                BEFORE INSERT OR UPDATE OF text ON transcript_segments
                FOR EACH ROW EXECUTE FUNCTION transcript_segments_tsv_update();
                """
            )
        )
    await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def prepare_database():
    asyncio.run(_prepare_database())
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
