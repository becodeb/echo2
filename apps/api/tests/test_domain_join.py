"""Alta automática por dominio (AUTO_JOIN_DOMAINS)."""
import asyncio
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from echo_api.config import get_settings

from conftest import TEST_DATABASE_URL, EchoTestUser


def _sql(statement: str, **params):
    async def run():
        engine = create_async_engine(TEST_DATABASE_URL)
        async with engine.begin() as connection:
            await connection.execute(text(statement), params)
        await engine.dispose()

    asyncio.run(run())


def _register(client, email: str) -> None:
    response = client.post(
        "/api/auth/register", json={"email": email, "password": "password123", "name": "Docente"}
    )
    assert response.status_code == 201, response.text


def _org_slug(client, owner: EchoTestUser) -> str:
    orgs = client.get("/api/auth/me", headers=owner.headers).json()["organizations"]
    return next(org["slug"] for org in orgs if org["id"] == owner.org_id)


def _refresh(client) -> dict:
    response = client.post("/api/auth/refresh", headers={"x-echo-client": "web"})
    assert response.status_code == 200, response.text
    return response.json()


def test_google_user_of_domain_joins_as_member(client, monkeypatch):
    owner = EchoTestUser(client, org_name="Colegio")
    domain = f"colegio-{uuid.uuid4().hex[:6]}.edu.ar"
    monkeypatch.setattr(get_settings(), "auto_join_domains", f"{domain}={_org_slug(client, owner)}")

    email = f"docente@{domain}"
    _register(client, email)
    _sql("update users set google_sub = :sub where email = :email", sub=uuid.uuid4().hex, email=email)

    orgs = _refresh(client)["organizations"]
    assert [(org["id"], org["role"]) for org in orgs] == [(owner.org_id, "member")]

    # Idempotente: un segundo refresh no duplica la membresía.
    assert len(_refresh(client)["organizations"]) == 1


def test_password_only_account_does_not_join(client, monkeypatch):
    """Sin Google el email no está verificado: no alcanza con escribir el dominio."""
    owner = EchoTestUser(client, org_name="Colegio")
    domain = f"colegio-{uuid.uuid4().hex[:6]}.edu.ar"
    monkeypatch.setattr(get_settings(), "auto_join_domains", f"{domain}={_org_slug(client, owner)}")

    _register(client, f"impostor@{domain}")

    assert _refresh(client)["organizations"] == []


def test_auto_join_domain_map_ignores_malformed_entries(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(
        settings, "auto_join_domains", " @Northfield.edu.ar = northfield-1 , roto, =x, y= "
    )
    assert settings.auto_join_domain_map == {"northfield.edu.ar": "northfield-1"}
