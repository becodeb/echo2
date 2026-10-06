"""Número de acta: correlativo por organización, fijo por acta y sin repetir."""
import asyncio

from conftest import TEST_DATABASE_URL, EchoTestUser
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def _meeting_with_minutes(client, user) -> tuple[str, str]:
    """Reunión con un acta escrita a mano: existe pero todavía sin número."""
    meeting_id = client.post("/api/meetings", json={"title": "Entrevista"}, headers=user.headers).json()["id"]
    saved = client.post(
        f"/api/meetings/{meeting_id}/minutes/versions",
        json={"body_markdown": "# ACTA\n\nTexto del acta."},
        headers=user.headers,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["number"] is None
    return meeting_id, saved.json()["id"]


def _print(client, user, meeting_id) -> int:
    response = client.post(f"/api/meetings/{meeting_id}/minutes/number", headers=user.headers)
    assert response.status_code == 200, response.text
    return response.json()["number"]


def test_numbers_are_sequential_and_fixed_per_acta(client):
    user = EchoTestUser(client, org_name="Colegio Numeración")
    first, _ = _meeting_with_minutes(client, user)
    second, _ = _meeting_with_minutes(client, user)

    assert _print(client, user, first) == 1
    assert _print(client, user, second) == 2
    # Reimprimir no gasta un número nuevo.
    assert _print(client, user, first) == 1
    assert client.get(f"/api/meetings/{first}/minutes", headers=user.headers).json()["number"] == 1


def test_each_organization_has_its_own_numbering(client):
    school_a = EchoTestUser(client, org_name="Sede A")
    school_b = EchoTestUser(client, org_name="Sede B")
    meeting_a, _ = _meeting_with_minutes(client, school_a)
    meeting_b, _ = _meeting_with_minutes(client, school_b)

    assert _print(client, school_a, meeting_a) == 1
    assert _print(client, school_b, meeting_b) == 1


def test_start_number_is_configurable_but_never_below_a_used_one(client):
    user = EchoTestUser(client, org_name="Colegio que se muda")
    assert client.get("/api/org/minutes-numbering", headers=user.headers).json() == {
        "next_number": 1,
        "last_assigned": None,
    }

    # Venía numerando en otro sistema: sigue desde el 500.
    moved = client.put("/api/org/minutes-numbering", json={"next_number": 500}, headers=user.headers)
    assert moved.status_code == 200, moved.text
    meeting_id, _ = _meeting_with_minutes(client, user)
    assert _print(client, user, meeting_id) == 500

    # Volver para atrás duplicaría el 500: se rechaza.
    back = client.put("/api/org/minutes-numbering", json={"next_number": 100}, headers=user.headers)
    assert back.status_code == 409
    assert "501" in back.json()["detail"]
    numbering = client.get("/api/org/minutes-numbering", headers=user.headers).json()
    assert numbering == {"next_number": 501, "last_assigned": 500}

    # Saltear números para adelante sí se puede.
    assert client.put("/api/org/minutes-numbering", json={"next_number": 600}, headers=user.headers).status_code == 200


def test_simultaneous_prints_never_share_a_number(client):
    """Dos personas imprimen a la vez: una recibe N y la otra N+1."""
    import uuid

    from echo_api.services.acta_number import ensure_number

    user = EchoTestUser(client, org_name="Colegio concurrente")
    ids = [uuid.UUID(_meeting_with_minutes(client, user)[1]) for _ in range(6)]

    async def run() -> list[int]:
        engine = create_async_engine(TEST_DATABASE_URL)
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        async def assign(minutes_id):
            async with sessions() as db:
                number = await ensure_number(db, minutes_id)
                await db.commit()
                return number

        try:
            # Cada acta dos veces, todo a la vez: seis actas distintas y
            # pedidos repetidos sobre la misma.
            return await asyncio.gather(*(assign(minutes_id) for minutes_id in ids + ids))
        finally:
            await engine.dispose()

    numbers = asyncio.run(run())
    first_pass, second_pass = numbers[:6], numbers[6:]
    assert sorted(first_pass) == [1, 2, 3, 4, 5, 6]
    # El mismo acta pedida dos veces a la vez recibe un solo número.
    assert first_pass == second_pass


def test_new_organization_starts_with_default_reasons(client):
    user = EchoTestUser(client, org_name="Colegio nuevo")
    reasons = client.get("/api/org/meeting-reasons", headers=user.headers).json()
    names = [reason["name"] for reason in reasons]
    assert "Desempeño académico" in names
    assert "Conducta" in names
    assert len(names) >= 10


def test_whoever_makes_the_acta_sets_its_number(client):
    # Bauti (6/10): hay actas que se hacen fuera de Echo, así que el número lo
    # pone la persona. Echo sugiere el siguiente al más alto y no deja repetir.
    user = EchoTestUser(client, org_name="Colegio Número a mano")
    first, _ = _meeting_with_minutes(client, user)
    second, _ = _meeting_with_minutes(client, user)

    set_first = client.put(f"/api/meetings/{first}/minutes/number", json={"number": 120}, headers=user.headers)
    assert set_first.status_code == 200 and set_first.json()["number"] == 120
    assert client.get("/api/org/minutes-numbering", headers=user.headers).json()["next_number"] == 121
    repeated = client.put(f"/api/meetings/{second}/minutes/number", json={"number": 120}, headers=user.headers)
    assert repeated.status_code == 409 and "120" in repeated.json()["detail"]
    # Corregirlo a uno libre, aunque sea menor, sí.
    assert client.put(f"/api/meetings/{second}/minutes/number", json={"number": 118},
                      headers=user.headers).json()["number"] == 118
    assert client.get(f"/api/meetings/{second}/minutes", headers=user.headers).json()["number"] == 118


def test_instructions_reach_the_acta_prompt():
    from echo_api.services.minutes_gen import instructions_block

    assert instructions_block(None) == "" and instructions_block("   ") == ""
    block = instructions_block("No incluir lo del hermano.\n\nQue figure la reunión con la psicopedagoga.")
    assert "No incluir lo del hermano. Que figure la reunión con la psicopedagoga." in block
    assert "sin inventar" in block
    assert len(instructions_block("x" * 5000)) < 1300


def test_making_the_acta_takes_the_number_and_the_instructions(client, monkeypatch):
    import echo_api.routers.minutes as minutes_router
    from echo_api.services.ai_settings import LLMConfig

    calls = []

    async def fake_resolve_llm(db, org_id):
        return LLMConfig("groq", "openai/gpt-oss-120b", "x")

    async def fake_generate(meeting_id, provider, instructions=None):
        calls.append(instructions)

    monkeypatch.setattr(minutes_router, "resolve_llm", fake_resolve_llm)
    monkeypatch.setattr(minutes_router, "generate_minutes", fake_generate)
    user = EchoTestUser(client, org_name="Colegio Hacer el acta")
    taken, _ = _meeting_with_minutes(client, user)
    client.put(f"/api/meetings/{taken}/minutes/number", json={"number": 7}, headers=user.headers)
    meeting_id = client.post("/api/meetings", json={"title": "Familia Romero"}, headers=user.headers).json()["id"]

    repeated = client.post(f"/api/meetings/{meeting_id}/minutes/generate", json={"number": 7}, headers=user.headers)
    assert repeated.status_code == 409 and calls == []
    started = client.post(
        f"/api/meetings/{meeting_id}/minutes/generate",
        json={"number": 8, "instructions": "No incluir lo del hermano."},
        headers=user.headers,
    )
    assert started.status_code == 202, started.text
    assert calls == ["No incluir lo del hermano."]
    assert client.get(f"/api/meetings/{meeting_id}/minutes", headers=user.headers).json()["number"] == 8
    # Sin cuerpo sigue andando (el pipeline y los reintentos).
    assert client.post(f"/api/meetings/{meeting_id}/minutes/generate", headers=user.headers).status_code == 202
