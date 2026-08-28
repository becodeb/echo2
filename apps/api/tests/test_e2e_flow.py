"""E2E del flujo completo (§74 del spec):

crear cuenta → org → reunión → grabar (WS con texto tipo bridge) → finalizar
→ pipeline (fakes) → resumen/decisiones/tareas → acta → chat → compartir →
volver a entrar y encontrarla.
"""
import json
import time

from conftest import EchoTestUser

from echo_api.config import get_settings

SCRIPT = [
    ("Tenemos que terminar la compra esta semana.", 0, 3000, "speaker_1"),
    ("Yo puedo pedir los presupuestos, los pido el viernes.", 3200, 6800, "speaker_2"),
    ("Perfecto, entonces el lanzamiento se mueve al viernes.", 7000, 10500, "speaker_1"),
    ("¿Cuánto cuesta la licencia anual?", 10800, 12500, "speaker_2"),
]


def _record_meeting(client, user, meeting_id):
    """Simula el recorder del navegador en modo bridge: manda TEXTO final."""
    with client.websocket_connect(
        f"/api/meetings/{meeting_id}/ws?token={user.token}"
    ) as websocket:
        websocket.send_text(json.dumps({"type": "hello", "role": "recorder", "sample_rate": 16000}))
        ack = json.loads(websocket.receive_text())
        assert ack["type"] == "hello_ack"
        assert ack["role"] == "recorder"

        for text, start, end, speaker in SCRIPT:
            websocket.send_text(
                json.dumps(
                    {
                        "type": "segment",
                        "text": text,
                        "start_ms": start,
                        "end_ms": end,
                        "confidence": 0.93,
                        "speaker_hint": speaker,
                    }
                )
            )
            event = json.loads(websocket.receive_text())
            assert event["type"] == "segment"
            assert event["text"] == text
            assert event["seq"] >= 1


def test_full_meeting_lifecycle(client, fake_ai):
    user = EchoTestUser(client, name="Ana Flujo", org_name="Org Flujo")

    # 1. crear reunión
    created = client.post(
        "/api/meetings",
        json={"title": "Reunión de dirección", "participants": [{"name": "Ana"}, {"name": "Marcos"}]},
        headers=user.headers,
    )
    assert created.status_code == 201
    meeting_id = created.json()["id"]

    # 2. iniciar
    started = client.post(f"/api/meetings/{meeting_id}/start", headers=user.headers)
    assert started.status_code == 200
    assert started.json()["status"] == "live"

    # 3. transcribir en vivo (modo bridge: el server recibe texto)
    _record_meeting(client, user, meeting_id)

    # 3b. marcador manual
    bookmark = client.post(
        f"/api/meetings/{meeting_id}/bookmarks",
        json={"kind": "decision", "at_ms": 8000, "note": "fecha confirmada"},
        headers=user.headers,
    )
    assert bookmark.status_code == 201

    # 4. finalizar → pipeline en background (fakes)
    finished = client.post(f"/api/meetings/{meeting_id}/finish", headers=user.headers)
    assert finished.status_code == 200
    assert finished.json()["status"] == "processing"

    # el TestClient ejecuta las background tasks al cerrar la respuesta;
    # esperar a completed con timeout
    deadline = time.time() + 30
    status = "processing"
    while time.time() < deadline:
        meeting = client.get(f"/api/meetings/{meeting_id}", headers=user.headers).json()
        status = meeting["status"]
        if status in ("completed", "failed"):
            break
        time.sleep(0.4)
    assert status == "completed", f"pipeline no completó: {meeting['processing_state']}"

    # 5. hablantes consolidados desde los hints
    assert len(meeting["speakers"]) == 2

    # 6. insights persistidos
    insights = client.get(f"/api/meetings/{meeting_id}/insights", headers=user.headers).json()
    assert any("viernes" in decision["text"] for decision in insights["decisions"])
    task = next(task for task in insights["action_items"] if task["assignee_name"] == "Marcos")
    assert task["due_text"] == "viernes"
    assert task["due_date"] is not None  # fecha relativa resuelta
    assert task["evidence_start_ms"] is not None  # referencia al transcript

    # 7. resumen
    summary = client.get(f"/api/meetings/{meeting_id}/summary", headers=user.headers).json()
    assert "executive" in summary
    assert len(summary["executive"]["content"]["points"]) >= 1

    # 8. acta generada + verificación
    minutes = client.get(f"/api/meetings/{meeting_id}/minutes", headers=user.headers).json()
    assert minutes is not None
    assert "ACTA" in minutes["version"]["body_markdown"]
    assert minutes["version"]["verification"], "el acta debe venir verificada"
    assert all(claim["status"] in ("verified", "weak", "missing") for claim in minutes["version"]["verification"])

    # 9. renombrar speaker → se refleja en el transcript
    speaker_id = meeting["speakers"][0]["id"]
    renamed = client.patch(
        f"/api/meetings/{meeting_id}/speakers/{speaker_id}",
        json={"display_name": "Ana"},
        headers=user.headers,
    )
    assert renamed.status_code == 200
    assert renamed.json()["display_name"] == "Ana"

    # 10. chat de la reunión con fuentes
    chat = client.post(
        f"/api/meetings/{meeting_id}/chat",
        json={"question": "¿Qué se decidió sobre el lanzamiento?"},
        headers=user.headers,
    )
    assert chat.status_code == 200
    chat_body = chat.json()
    assert chat_body["answer"]
    assert len(chat_body["sources"]) >= 1
    assert chat_body["sources"][0]["start_ms"] is not None

    # 11. editar transcript conserva historial
    transcript = client.get(f"/api/meetings/{meeting_id}/transcript", headers=user.headers).json()
    segment = transcript["segments"][0]
    edited = client.patch(
        f"/api/meetings/{meeting_id}/transcript/{segment['id']}",
        json={"text": "Tenemos que terminar la compra esta misma semana."},
        headers=user.headers,
    )
    assert edited.status_code == 200
    assert edited.json()["edited"] is True
    history = client.get(
        f"/api/meetings/{meeting_id}/transcript/{segment['id']}/history", headers=user.headers
    ).json()
    assert len(history) == 1
    assert history[0]["previous_text"] == segment["text"]

    # 12. compartir por link público
    link = client.post(
        f"/api/meetings/{meeting_id}/share-links",
        json={"role": "viewer", "expires_days": 7},
        headers=user.headers,
    )
    assert link.status_code == 201
    token = link.json()["token"]
    public = client.get(f"/api/shared/{token}")
    assert public.status_code == 200
    assert public.json()["meeting"]["title"] == "Reunión de dirección"
    assert len(public.json()["transcript"]) == len(SCRIPT)

    # 13. cerrar sesión y volver a entrar: la reunión sigue ahí
    client.post("/api/auth/logout")
    login = client.post(
        "/api/auth/login", json={"email": user.email, "password": user.password}
    )
    assert login.status_code == 200
    new_token = login.json()["access_token"]
    listing = client.get(
        "/api/meetings",
        headers={"Authorization": f"Bearer {new_token}", "X-Organization-Id": user.org_id},
    ).json()
    assert any(item["id"] == meeting_id for item in listing)

    # 14. búsqueda global la encuentra por contenido hablado
    results = client.get(
        "/api/search?q=lanzamiento",
        headers={"Authorization": f"Bearer {new_token}", "X-Organization-Id": user.org_id},
    ).json()
    assert any(hit["meeting_id"] == meeting_id for hit in results["transcript"])


def test_cloud_audio_mode_stores_nothing_without_stt(client, monkeypatch):
    """Sin STT configurado, mandar audio binario devuelve error claro (no simula)."""
    # El entorno real puede tener keys cargadas (ej. OPENAI_API_KEY para STT):
    # este test es sobre la ausencia de proveedor, así que la fuerza explícitamente
    # en vez de depender de que el .env del desarrollador esté vacío.
    settings = get_settings()
    for field in ("openai_api_key", "groq_api_key", "deepgram_api_key"):
        monkeypatch.setattr(settings, field, "")

    user = EchoTestUser(client, name="Sin STT", org_name="Org SinSTT")
    created = client.post("/api/meetings", json={"title": "Audio"}, headers=user.headers)
    meeting_id = created.json()["id"]
    client.post(f"/api/meetings/{meeting_id}/start", headers=user.headers)

    with client.websocket_connect(f"/api/meetings/{meeting_id}/ws?token={user.token}") as ws:
        ws.send_text(json.dumps({"type": "hello", "role": "recorder", "sample_rate": 16000}))
        ws.receive_text()
        # 7 segundos de silencio PCM16 → supera la ventana y fuerza resolución STT
        ws.send_bytes(b"\x00\x00" * 16000 * 7)
        event = json.loads(ws.receive_text())
        assert event["type"] == "error"
        assert event["code"] == "stt_not_configured"


def test_export_minutes_formats(client, fake_ai):
    user = EchoTestUser(client, name="Exporta", org_name="Org Export")
    created = client.post("/api/meetings", json={"title": "Para exportar"}, headers=user.headers)
    meeting_id = created.json()["id"]
    client.post(f"/api/meetings/{meeting_id}/start", headers=user.headers)
    _record_meeting(client, user, meeting_id)
    client.post(f"/api/meetings/{meeting_id}/finish", headers=user.headers)

    deadline = time.time() + 30
    while time.time() < deadline:
        meeting = client.get(f"/api/meetings/{meeting_id}", headers=user.headers).json()
        if meeting["status"] in ("completed", "failed"):
            break
        time.sleep(0.4)

    for fmt, content_type in [
        ("md", "text/markdown"),
        ("txt", "text/plain"),
        ("docx", "officedocument"),
        ("pdf", "application/pdf"),
    ]:
        response = client.get(
            f"/api/meetings/{meeting_id}/export/minutes.{fmt}", headers=user.headers
        )
        assert response.status_code == 200, f"export {fmt}: {response.text[:100]}"
        assert content_type in response.headers["content-type"]
        assert len(response.content) > 50
