"""Olvidé mi contraseña: link de un solo uso, sin decir si el mail existe."""
import re
import uuid
from datetime import UTC, datetime, timedelta

from conftest import EchoTestUser
from test_levels import _sql
from test_voice import _sql_rows


def _link_for(admin_id: str) -> str:
    [(body,)] = _sql_rows(
        "SELECT body FROM notifications WHERE user_id = :u AND kind = 'password_reset' ORDER BY created_at DESC LIMIT 1",
        u=admin_id,
    )
    return re.search(r"token=([\w-]+)", body).group(1)


def test_forgotten_password_can_be_reset_once(client):
    admin = EchoTestUser(client, org_name="Becode")
    _sql("UPDATE users SET is_superadmin = true WHERE id = :id", id=admin.user_id)
    email = f"olvido-{uuid.uuid4().hex[:6]}@test.dev"
    client.post("/api/auth/register", json={"email": email, "password": "vieja-1234", "name": "Olvido"})

    # Igual respuesta exista o no la cuenta.
    assert client.post("/api/auth/password/forgot", json={"email": "nadie@test.dev"}).status_code == 202
    assert client.post("/api/auth/password/forgot", json={"email": email}).status_code == 202
    token = _link_for(admin.user_id)  # sin mail configurado, le llega a Becode

    assert client.post("/api/auth/password/reset", json={"token": token, "password": "corta"}).status_code == 422
    assert client.post("/api/auth/password/reset", json={"token": token, "password": "nueva-12345"}).status_code == 200
    assert client.post("/api/auth/password/reset", json={"token": token, "password": "otra-12345"}).status_code == 400
    assert client.post("/api/auth/login", json={"email": email, "password": "vieja-1234"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": email, "password": "nueva-12345"}).status_code == 200


def test_an_old_link_does_not_work(client):
    admin = EchoTestUser(client, org_name="Becode")
    _sql("UPDATE users SET is_superadmin = true WHERE id = :id", id=admin.user_id)
    user = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    email = _sql_rows("SELECT email FROM users WHERE id = :id", id=user.user_id)[0][0]
    client.post("/api/auth/password/forgot", json={"email": email})
    token = _link_for(admin.user_id)
    _sql("UPDATE password_resets SET expires_at = :t", t=datetime.now(UTC) - timedelta(minutes=1))
    assert client.post("/api/auth/password/reset", json={"token": token, "password": "nueva-12345"}).status_code == 400


def test_using_a_link_voids_the_ones_asked_before(client):
    admin = EchoTestUser(client, org_name="Becode")
    _sql("UPDATE users SET is_superadmin = true WHERE id = :id", id=admin.user_id)
    user = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    email = _sql_rows("SELECT email FROM users WHERE id = :id", id=user.user_id)[0][0]
    client.post("/api/auth/password/forgot", json={"email": email})
    first = _link_for(admin.user_id)
    client.post("/api/auth/password/forgot", json={"email": email})
    second = _link_for(admin.user_id)
    assert first != second
    assert client.post("/api/auth/password/reset", json={"token": second, "password": "nueva-12345"}).status_code == 200
    # El primero (que pudo quedar en otro mail) ya no sirve.
    assert client.post("/api/auth/password/reset", json={"token": first, "password": "otra-12345"}).status_code == 400
