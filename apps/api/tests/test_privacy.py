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
