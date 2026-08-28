"""Auth: registro, login, refresh, sesión."""
import uuid


def test_register_login_me(client):
    email = f"reg-{uuid.uuid4().hex[:8]}@test.echo"
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "name": "Registro Test"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["access_token"]
    assert body["user"]["email"] == email
    assert body["organizations"] == []

    # login con contraseña incorrecta
    bad = client.post("/api/auth/login", json={"email": email, "password": "incorrecta1"})
    assert bad.status_code == 401

    # login correcto
    good = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    assert good.status_code == 200
    token = good.json()["access_token"]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["user"]["email"] == email


def test_register_duplicate_email(client):
    email = f"dup-{uuid.uuid4().hex[:8]}@test.echo"
    first = client.post(
        "/api/auth/register", json={"email": email, "password": "password123", "name": "Uno"}
    )
    assert first.status_code == 201
    second = client.post(
        "/api/auth/register", json={"email": email, "password": "password123", "name": "Dos"}
    )
    assert second.status_code == 409


def test_refresh_rotates_cookie(client):
    email = f"ref-{uuid.uuid4().hex[:8]}@test.echo"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "name": "Refresh Test"},
    )
    # el TestClient conserva cookies: refresh debe emitir nuevo access token
    refreshed = client.post("/api/auth/refresh", headers={"x-echo-client": "web"})
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]

    # sin el header anti-CSRF se rechaza
    rejected = client.post("/api/auth/refresh")
    assert rejected.status_code == 403


def test_me_requires_token(client):
    assert client.get("/api/auth/me").status_code == 401
    assert (
        client.get("/api/auth/me", headers={"Authorization": "Bearer invalido"}).status_code == 401
    )
