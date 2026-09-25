"""Alta sin invitación: por dominio (AUTO_JOIN_DOMAINS o join_rules) y por email."""
import asyncio
import json
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


def _register(client, email: str) -> dict:
    """Registra y deja la cookie de sesión de esta persona en el cliente."""
    response = client.post(
        "/api/auth/register", json={"email": email, "password": "password123", "name": "Docente"}
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _link_google(email: str) -> None:
    _sql("update users set google_sub = :sub where email = :email", sub=uuid.uuid4().hex, email=email)


def _set_rules(org_id: str, rules: list[str]) -> None:
    _sql("update organizations set join_rules = cast(:rules as jsonb) where id = :id", rules=json.dumps(rules), id=org_id)


def _org_slug(client, owner: EchoTestUser) -> str:
    orgs = client.get("/api/auth/me", headers=owner.headers).json()["organizations"]
    return next(org["slug"] for org in orgs if org["id"] == owner.org_id)


def _refresh(client) -> dict:
    response = client.post("/api/auth/refresh", headers={"x-echo-client": "web"})
    assert response.status_code == 200, response.text
    return response.json()


def _domain() -> str:
    return f"colegio-{uuid.uuid4().hex[:6]}.edu.ar"


def test_google_user_of_domain_joins_as_member(client, monkeypatch):
    owner = EchoTestUser(client, org_name="Colegio")
    domain = _domain()
    monkeypatch.setattr(get_settings(), "auto_join_domains", f"{domain}={_org_slug(client, owner)}")

    email = f"docente@{domain}"
    _register(client, email)
    _link_google(email)

    orgs = _refresh(client)["organizations"]
    assert [(org["id"], org["role"]) for org in orgs] == [(owner.org_id, "member")]

    # Idempotente: un segundo refresh no duplica la membresía.
    assert len(_refresh(client)["organizations"]) == 1


def test_password_only_account_does_not_join_and_is_told_to_use_google(client, monkeypatch):
    """Sin Google el email no está verificado: no alcanza con escribir el dominio."""
    owner = EchoTestUser(client, org_name="Colegio Contraseña")
    domain = _domain()
    monkeypatch.setattr(get_settings(), "auto_join_domains", f"{domain}={_org_slug(client, owner)}")

    headers = _register(client, f"impostor@{domain}")

    assert _refresh(client)["organizations"] == []
    options = client.get("/api/auth/join-options", headers=headers).json()
    assert options["requires_google"] is True
    assert [org["name"] for org in options["organizations"]] == ["Colegio Contraseña"]
    joined = client.post("/api/auth/join", json={"organization_id": owner.org_id}, headers=headers)
    assert joined.status_code == 403


def test_join_rule_with_a_single_organization_joins_directly(client):
    owner = EchoTestUser(client, org_name="Colegio Único")
    domain = _domain()
    _set_rules(owner.org_id, [domain])

    email = f"preceptor@{domain}"
    _register(client, email)
    _link_google(email)

    assert [org["id"] for org in _refresh(client)["organizations"]] == [owner.org_id]


def test_domain_shared_by_two_campuses_asks_which_one(client):
    """Northfield Puertos y Northfield Nordelta comparten dominio: se elige sede."""
    puertos = EchoTestUser(client, org_name="Northfield Puertos")
    nordelta = EchoTestUser(client, org_name="Northfield Nordelta")
    domain = _domain()
    _set_rules(puertos.org_id, [domain])
    _set_rules(nordelta.org_id, [domain])

    email = f"docente@{domain}"
    headers = _register(client, email)
    _link_google(email)

    # No entra sola a ninguna: no hay forma de saber cuál es la suya.
    assert _refresh(client)["organizations"] == []
    options = client.get("/api/auth/join-options", headers=headers).json()
    assert options["requires_google"] is False
    assert sorted(org["name"] for org in options["organizations"]) == ["Northfield Nordelta", "Northfield Puertos"]

    joined = client.post("/api/auth/join", json={"organization_id": nordelta.org_id}, headers=headers)
    assert joined.status_code == 200, joined.text
    assert joined.json()["role"] == "member"

    # Ya eligió: no se le vuelve a preguntar ni se la suma a la otra sede.
    assert client.get("/api/auth/join-options", headers=headers).json()["organizations"] == []
    assert [org["id"] for org in _refresh(client)["organizations"]] == [nordelta.org_id]


def test_cannot_join_an_organization_the_email_does_not_match(client):
    other = EchoTestUser(client, org_name="Otro colegio")
    _set_rules(other.org_id, [_domain()])

    email = f"alguien@{_domain()}"
    headers = _register(client, email)
    _link_google(email)

    joined = client.post("/api/auth/join", json={"organization_id": other.org_id}, headers=headers)
    assert joined.status_code == 403


def test_exact_email_joins_every_organization_that_lists_it(client):
    """Una persona puntual (ej. una directora con Gmail) asignada a las dos sedes."""
    puertos = EchoTestUser(client, org_name="Sede Puertos")
    nordelta = EchoTestUser(client, org_name="Sede Nordelta")
    email = f"mariana.{uuid.uuid4().hex[:6]}@gmail.com"
    _set_rules(puertos.org_id, [email])
    _set_rules(nordelta.org_id, [email])

    _register(client, email)
    _link_google(email)

    assert sorted(org["id"] for org in _refresh(client)["organizations"]) == sorted(
        [puertos.org_id, nordelta.org_id]
    )


def test_superadmin_sets_join_rules_and_public_domains_are_rejected(client):
    admin = EchoTestUser(client, org_name="Instalación")
    school = EchoTestUser(client, org_name="Colegio Reglas")
    _sql("update users set is_superadmin = true where id = :id", id=admin.user_id)
    url = f"/api/admin/organizations/{school.org_id}/join-rules"
    headers = {"Authorization": f"Bearer {admin.token}"}

    saved = client.put(url, json={"rules": [" @Northfield.edu.ar ", "Mariana@Gmail.com", "", "northfield.edu.ar"]}, headers=headers)
    assert saved.status_code == 200, saved.text
    assert saved.json() == ["northfield.edu.ar", "mariana@gmail.com"]

    public = client.put(url, json={"rules": ["gmail.com"]}, headers=headers)
    assert public.status_code == 422
    assert "público" in public.json()["detail"]

    # Para quien no es superadmin el panel no existe.
    not_admin = client.put(url, json={"rules": ["x.edu.ar"]}, headers={"Authorization": f"Bearer {school.token}"})
    assert not_admin.status_code == 404


def test_auto_join_domain_map_ignores_malformed_entries_and_allows_several_campuses(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "auto_join_domains",
        " @Northfield.edu.ar = northfield-1 , roto, =x, y= , northfield.edu.ar=northfield-2",
    )
    assert settings.auto_join_domain_map == {"northfield.edu.ar": ["northfield-1", "northfield-2"]}
