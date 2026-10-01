"""Seudonimización: ningún nombre conocido sale hacia la IA, y todo vuelve."""
import asyncio

from echo_api.services.llm.base import LLMProvider
from echo_api.services.privacy import Person, PrivateLLMProvider, Pseudonymizer


def roster() -> list[Person]:
    group = "FLIA. MUNAFO (Larrubia)"
    return [
        Person.parse("MUNAFO, Allegra", "alumno", group, {"curso": "1N EP"}),
        Person.parse("LARRUBIA, Melina", "madre", group),
        Person.parse("MUNAFO, Ricardo", "padre", group),
        Person.parse("GIBSON, Mariana", "personal"),
        # Otra alumna con el mismo nombre de pila que una madre de otra familia.
        Person.parse("PEREZ, Martina", "alumno", "FLIA. PEREZ"),
        Person.parse("GOMEZ, Martina", "madre", "FLIA. GOMEZ"),
    ]


TRANSCRIPT = (
    "[00:00] Directora: Soy Mariana Gibson. Hoy vino la mamá de Allegra Munafo.\n"
    "[00:08] Madre: Soy Melina. Allegra llega triste, Ricardo también lo notó.\n"
    "[00:16] Madre: Mi DNI es 32.456.789 y mi mail melina@correo.com, tel 11 4567-8901.\n"
    "[00:24] Directora: Martina también estaba en el recreo, en el campo de deportes."
)


def test_no_sale_ningun_nombre_ni_dato():
    pseudo = Pseudonymizer(roster())
    safe = pseudo.apply(TRANSCRIPT)
    for leaked in ("Mariana", "Gibson", "Allegra", "Munafo", "Melina", "Ricardo", "32.456.789",
                   "melina@correo.com", "4567-8901", "Martina"):
        assert leaked not in safe, (leaked, safe)
    # El nombre completo y el nombre de pila de la misma persona: mismo marcador.
    assert safe.count("[ALUMNO_1]") == 2
    # Nombrar a la alumna vuelve reconocible a su familia por nombre de pila.
    assert "[MADRE_1]" in safe and "[PADRE_1]" in safe
    # Minúscula no es nombre propio: "campo" queda.
    assert "campo de deportes" in safe


def test_nombre_ambiguo_lleva_marcador_generico_y_se_restaura():
    pseudo = Pseudonymizer(roster())
    safe = pseudo.apply("Martina no vino.")
    assert safe.startswith("[NOMBRE_")
    assert pseudo.restore(safe) == "Martina no vino."


def test_restaura_lo_que_devuelve_la_ia():
    pseudo = Pseudonymizer(roster())
    pseudo.apply(TRANSCRIPT)
    answer = '{"alumno": "[ALUMNO_1]", "con": "la Sra. [MADRE_1]", "nota": "llamar al NUMERO_1"}'
    restored = pseudo.restore(answer)
    assert '"alumno": "Allegra Munafo"' in restored
    assert "la Sra. Melina Larrubia" in restored
    assert "32.456.789" in restored  # también sin corchetes


def test_marcadores_estables_entre_llamadas():
    pseudo = Pseudonymizer(roster())
    first = pseudo.apply("Habló Allegra Munafo.")
    second = pseudo.apply("Allegra estaba bien.")
    assert first == "Habló [ALUMNO_1]." and second == "[ALUMNO_1] estaba bien."


def test_no_toca_fechas_ni_milisegundos():
    pseudo = Pseudonymizer(roster())
    text = 'El 23-09-2026 a las 10.\n{"evidencia_ms": 1234567}'
    assert pseudo.apply(text) == text


def test_participante_de_la_reunion_desambigua():
    # "Martina" es ambiguo en la nómina, pero en ESTA reunión hay una sola.
    pseudo = Pseudonymizer(roster(), priority_people=[Person.parse("Martina Perez", "persona")])
    assert pseudo.apply("Martina dijo que sí.") == "[PERSONA_1] dijo que sí."


def test_el_wrapper_nunca_manda_nombres_y_devuelve_restaurado():
    class Spy(LLMProvider):
        name = "spy"
        model = "spy-1"

        def __init__(self):
            self.seen = ""

        async def chat(self, system, messages, temperature=0.2, max_tokens=4096):
            self.seen = system + "\n" + "\n".join(m["content"] for m in messages)
            return "Acta: [ALUMNO_1] y [MADRE_1]."

    spy = Spy()
    provider = PrivateLLMProvider(spy, Pseudonymizer(roster()))
    answer = asyncio.run(provider.chat("Redactá el acta.", [{"role": "user", "content": TRANSCRIPT}]))
    assert "Allegra" not in spy.seen and "Melina" not in spy.seen
    assert "Privacidad:" in spy.seen
    assert answer == "Acta: Allegra Munafo y Melina Larrubia."


def test_nombre_de_usuario_con_sede_no_censura_la_sede():
    person = Person.parse("Analía Oliver - Northfield Puertos", "personal")
    assert person.display == "Analía Oliver"
    assert Pseudonymizer([person]).apply("Colegio Northfield") == "Colegio Northfield"


def test_persona_detras_de_un_nombre_restaurado():
    pseudo = Pseudonymizer(roster())
    pseudo.apply("Vino Allegra Munafo.")
    student = pseudo.person_for_token_text(pseudo.restore("[ALUMNO_1]"))
    assert student.formal == "MUNAFO, Allegra"
    assert student.extra["curso"] == "1N EP"


def test_meses_no_se_censuran_aunque_sean_nombres():
    pseudo = Pseudonymizer([Person.parse("GARCIA, Abril", "alumno")])
    assert pseudo.apply("Nos vemos el 3 de Abril.") == "Nos vemos el 3 de Abril."
    # Con apellido sí: ahí es la persona.
    assert pseudo.apply("Vino Abril Garcia.") == "Vino [ALUMNO_1]."


def test_nombre_de_pila_compuesto_se_reconoce_entero():
    madre = Person.parse("Castro, Maria Del Pilar", "madre", "FLIA. ALOISE (Castro)")
    assert madre.display == "Maria del Pilar Castro"
    pseudo = Pseudonymizer([madre, Person.parse("PEREZ, Maria", "alumno")])
    safe = pseudo.apply("Hola, soy Maria del Pilar, la mamá.")
    assert safe == "Hola, soy [MADRE_1], la mamá."
    assert pseudo.restore("la Sra. [MADRE_1]") == "la Sra. Maria del Pilar Castro"


# ── Nombres que detectó la pasada final ──────────────────────────


def test_detected_names_do_not_repeat_parts_of_a_full_name():
    from echo_api.services.privacy import detected_names

    # Lo que devolvió Scribe en la reunión del 27/9 (tests/fixtures/scribe_2026-09-27.json).
    meta = {"detected_entities": [
        {"text": "Bautista Goñi", "type": "name"}, {"text": "Bautista", "type": "name_given"},
        {"text": "Goñi", "type": "name_family"}, {"text": "Vanina", "type": "name"},
        {"text": "Vanina", "type": "name_given"}, {"text": "profe", "type": "occupation"},
        {"text": "tres", "type": "cardinal"},
    ]}
    assert detected_names(meta) == ["Bautista Goñi", "Vanina"]
    assert detected_names(None) == []


def test_a_name_in_no_roster_does_not_reach_the_ai(client):
    import json
    import uuid

    from conftest import EchoTestUser
    from test_levels import _sql

    from echo_api.db import SessionLocal

    user = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    meeting = client.post("/api/meetings", json={"title": "x", "level": "primaria"}, headers=user.headers).json()
    meta = {"detected_entities": [{"text": "Vanina", "type": "name"}, {"text": "Ezequiel Toranzo", "type": "name"}]}
    _sql("UPDATE meetings SET meta = CAST(:meta AS jsonb) WHERE id = :id", meta=json.dumps(meta), id=meeting["id"])

    sent: list[str] = []

    class Spy(LLMProvider):
        async def chat(self, system, messages, temperature=0.2, max_tokens=4096):
            sent.append(system + " ".join(m["content"] for m in messages))
            return "Hablaron [PERSONA_1] y [PERSONA_2]."

    async def run():
        from echo_api.services.privacy import protect

        async with SessionLocal() as db:
            provider = await protect(db, uuid.UUID(user.org_id), Spy(), uuid.UUID(meeting["id"]))
            return await provider.chat("Resumí.", [{"role": "user", "content": "Soy Vanina. Ezequiel Toranzo no vino, Toranzo avisó."}])

    answer = asyncio.run(run())
    assert sent and "Vanina" not in sent[0] and "Toranzo" not in sent[0] and "Ezequiel" not in sent[0]
    assert answer == "Hablaron Vanina y Ezequiel Toranzo."


def test_a_name_outside_every_list_is_covered_without_scribe():
    """Pasada con Groq (Gratis, menores): sin entidades de Scribe. Lo que tiene
    pinta de nombre propio a mitad de oración tampoco sale (reunión del 1/10)."""
    text = (
        "[00:01] Persona 1: ¿Qué hacés, Bauti?\n"
        "[00:03] Persona 2: ¿Todo bien, Lau? Tenemos que probar la app de Andy en el colegio.\n"
        "[00:45] Persona 1: Yo hablo con Carla Curto y con Cristian. Bueno, dale.\n"
        "[00:50] Persona 2: El Colegio y la colegio... Martina viene el lunes."
    )
    pseudo = Pseudonymizer(roster())
    safe = pseudo.apply(text)
    for name in ("Bauti", "Lau", "Andy", "Carla", "Curto", "Cristian"):
        assert name not in safe, name
    # Lo que también aparece en minúscula, o abre la oración, no se toca.
    assert "El Colegio" in safe and "Bueno, dale" in safe and "Persona 1:" in safe
    assert "[NOMBRE_" in safe and pseudo.restore(safe) == text


def test_instructions_are_not_guessed_but_the_transcript_is():
    seen = {}

    class Spy(LLMProvider):
        name = "spy"

        async def chat(self, system, messages, temperature=0.2, max_tokens=4096):
            seen["system"], seen["user"] = system, messages[-1]["content"]
            return "Hablaste con [NOMBRE_1]."

    wrapped = PrivateLLMProvider(Spy(), Pseudonymizer([]))
    answer = asyncio.run(wrapped.chat("Sos Echo, el asistente de la Dirección.",
                                      [{"role": "user", "content": "Lo dijo hoy Ludmila en la reunión."}]))
    assert "Ludmila" not in seen["user"] and "Echo" in seen["system"] and "Dirección" in seen["system"]
    assert answer == "Hablaste con Ludmila."


def test_personal_and_health_data_that_scribe_heard_is_covered():
    from echo_api.services.privacy import detected_data

    meta = {"detected_entities": [
        {"text": "Bautista Goñi", "type": "name"}, {"text": "uno", "type": "cardinal"},
        {"text": "profe", "type": "occupation"}, {"text": "Avenida Libertador 1450", "type": "location_address"},
        {"text": "TDAH", "type": "medical_condition"}, {"text": "metilfenidato", "type": "medication"},
    ]}
    data = detected_data(meta)
    assert data == ["Avenida Libertador 1450", "TDAH", "metilfenidato"]
    pseudo = Pseudonymizer([], data=data)
    text = "Uno, dos. La profe dijo que vive en avenida libertador 1450, tiene TDAH y toma Metilfenidato."
    safe = pseudo.apply(text)
    assert "libertador" not in safe.lower() and "TDAH" not in safe and "etilfenidato" not in safe
    assert safe.startswith("Uno, dos. La profe") and "[DATO_" in safe
    assert pseudo.restore(safe) == text
