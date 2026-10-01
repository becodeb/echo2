"""Contacto con Becode sin mostrar el mail, y pedido de baja de la cuenta."""
import uuid

from conftest import EchoTestUser
from test_levels import _sql
from test_voice import _sql_rows


def test_anyone_can_write_to_becode_without_seeing_an_email(client):
    admin = EchoTestUser(client, org_name="Becode")
    _sql("UPDATE users SET is_superadmin = true WHERE id = :id", id=admin.user_id)
    sent = client.post("/api/contact", json={
        "name": "Ana Ruiz", "email": "ana@colegio.edu.ar", "topic": "privacidad",
        "organization": "Colegio Sur", "message": "Quiero saber qué datos tienen de mí.",
    })
    assert sent.status_code == 202
    [(title, body)] = _sql_rows(
        "SELECT title, body FROM notifications WHERE user_id = :u AND kind = 'contact'", u=admin.user_id)
    assert "Mis datos" in title and "Ana Ruiz" in title and "ana@colegio.edu.ar" in body
    # Un bot que completa el campo oculto no le llega a nadie.
    client.post("/api/contact", json={"name": "x", "email": "x@x.com", "message": "spam", "website": "http://x"})
    assert len(_sql_rows("SELECT id FROM notifications WHERE user_id = :u AND kind = 'contact'", u=admin.user_id)) == 1
    assert client.post("/api/contact", json={"name": "x", "email": "no-es-mail", "message": "hola"}).status_code == 422


def test_asking_to_delete_the_account_reaches_becode_once(client):
    admin = EchoTestUser(client, org_name="Becode")
    _sql("UPDATE users SET is_superadmin = true WHERE id = :id", id=admin.user_id)
    user = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    assert client.get("/api/me/deletion-request", headers=user.headers).json() == {"requested_at": None}
    first = client.post("/api/me/deletion-request", headers=user.headers).json()
    assert first["requested_at"]
    again = client.post("/api/me/deletion-request", headers=user.headers).json()
    assert again == first
    titles = [t for (t,) in _sql_rows("SELECT title FROM notifications WHERE user_id = :u AND kind = 'contact'",
                                      u=admin.user_id)]
    assert sum("pidió la baja" in t for t in titles) == 1
    assert client.post("/api/me/deletion-request").status_code == 401
