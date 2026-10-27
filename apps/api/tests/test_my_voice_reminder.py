"""Grabar "Mi voz" es "medio obligatorio" (pedido de Bauti, 27/10).

La invitación ya no se apaga para siempre ("Más tarde" dura un día) y la
campanita lo recuerda cada 3 días sin apilar notificaciones
(services/voice_reminder.py).
"""
import asyncio
import io
import uuid
import wave

from conftest import EchoTestUser
from test_levels import _sql, _sql_rows
from test_voice_names import BAUTI

from echo_api.services import voiceprint
from echo_api.services.voice_reminder import VOICE_REMINDER_KIND, remind_missing_voices


def _reminders(user: EchoTestUser) -> list[tuple]:
    return _sql_rows(
        "SELECT id::text, organization_id::text, read_at IS NULL FROM notifications WHERE user_id = :u AND kind = :k",
        u=user.user_id, k=VOICE_REMINDER_KIND,
    )


def test_later_lasts_a_day_and_the_old_never_asks_again(client):
    user = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    assert client.get("/api/me/voice", headers=user.headers).json()["prompt_seen"] is False
    assert client.post("/api/me/voice/prompt-seen", headers=user.headers).status_code == 204
    assert client.get("/api/me/voice", headers=user.headers).json()["prompt_seen"] is True
    # Quien eligió "No volver a mostrar" antes del cambio (o "Más tarde" ayer) la vuelve a ver.
    _sql("UPDATE users SET voice_prompt_seen_at = now() - interval '2 days' WHERE id = :u", u=user.user_id)
    assert client.get("/api/me/voice", headers=user.headers).json()["prompt_seen"] is False


def test_reminder_once_then_every_three_days_until_recorded(client, monkeypatch):
    user = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    asyncio.run(remind_missing_voices())
    asyncio.run(remind_missing_voices())
    [(reminder_id, org_id, unread)] = [row for row in _reminders(user) if row[1] == user.org_id]
    assert unread
    listed = client.get("/api/notifications", headers=user.headers).json()["notifications"]
    assert [item["link"] for item in listed if item["kind"] == VOICE_REMINDER_KIND] == ["/settings/my-voice"]

    # Leída: no vuelve enseguida, pero sí pasados 3 días, y sigue siendo una sola.
    client.post(f"/api/notifications/{reminder_id}/read", headers=user.headers)
    asyncio.run(remind_missing_voices())
    assert all(not unread for _, _, unread in _reminders(user))
    _sql("UPDATE notifications SET read_at = now() - interval '4 days' WHERE user_id = :u AND kind = :k",
         u=user.user_id, k=VOICE_REMINDER_KIND)
    asyncio.run(remind_missing_voices())
    again = [row for row in _reminders(user) if row[1] == user.org_id]
    assert again == [(reminder_id, org_id, True)]

    # Al grabarla se va, y no vuelve.
    monkeypatch.setattr(voiceprint, "embed", lambda samples: BAUTI)
    from test_speakers import _tone

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(_tone(10.0))
    saved = client.post("/api/me/voice", files={"audio": ("voz.wav", buffer.getvalue(), "audio/wav")},
                        data={"consent": "true"}, headers={"Authorization": f"Bearer {user.token}"})
    assert saved.status_code == 200, saved.text
    assert _reminders(user) == []
    asyncio.run(remind_missing_voices())
    assert _reminders(user) == []

    # Una muestra de antes del mínimo de 8 s no sirve: se le vuelve a pedir.
    _sql("UPDATE user_voice_samples SET duration_ms = 4700 WHERE user_id = :u", u=user.user_id)
    asyncio.run(remind_missing_voices())
    assert [row[2] for row in _reminders(user) if row[1] == user.org_id] == [True]
