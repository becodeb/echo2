"""Unit tests: fechas relativas, parseo LLM, chunking RAG, contexto del verificador."""
from datetime import date

from echo_api.services.dates import resolve_relative_date
from echo_api.services.llm.base import parse_json_loose
from echo_api.services.minutes_gen import _claim_context
from echo_api.services.pipeline import _split_sections
from echo_api.services.transcript_util import format_ms

# miércoles 26 de agosto de 2026
REF = date(2026, 8, 26)


class TestFechasRelativas:
    def test_dias_simples(self):
        assert resolve_relative_date("hoy", REF) == REF
        assert resolve_relative_date("mañana", REF) == date(2026, 8, 27)
        assert resolve_relative_date("tomorrow", REF) == date(2026, 8, 27)

    def test_dia_de_semana(self):
        # miércoles → "viernes" = viernes 28
        assert resolve_relative_date("viernes", REF) == date(2026, 8, 28)
        assert resolve_relative_date("el viernes", REF) == date(2026, 8, 28)
        # "miércoles" dicho un miércoles = el próximo (no hoy)
        assert resolve_relative_date("miércoles", REF) == date(2026, 9, 2)
        assert resolve_relative_date("friday", REF) == date(2026, 8, 28)

    def test_en_n_unidades(self):
        assert resolve_relative_date("en 3 días", REF) == date(2026, 8, 29)
        assert resolve_relative_date("en 2 semanas", REF) == date(2026, 9, 9)
        assert resolve_relative_date("in 1 week", REF) == date(2026, 9, 2)

    def test_fecha_explicita(self):
        assert resolve_relative_date("15 de septiembre", REF) == date(2026, 9, 15)
        # mes ya pasado sin año → año próximo
        assert resolve_relative_date("15 de enero", REF) == date(2027, 1, 15)
        assert resolve_relative_date("15/09", REF) == date(2026, 9, 15)
        assert resolve_relative_date("15/09/2027", REF) == date(2027, 9, 15)
        assert resolve_relative_date("2026-10-01", REF) == date(2026, 10, 1)

    def test_expresiones(self):
        assert resolve_relative_date("fin de mes", REF) == date(2026, 8, 31)
        assert resolve_relative_date("la próxima semana", REF) == date(2026, 8, 31)

    def test_no_resoluble(self):
        assert resolve_relative_date("cuando se pueda", REF) is None
        assert resolve_relative_date(None, REF) is None
        assert resolve_relative_date("", REF) is None


class TestParseJsonLoose:
    def test_json_directo(self):
        assert parse_json_loose('{"a": 1}') == {"a": 1}

    def test_json_con_fence(self):
        assert parse_json_loose('```json\n{"a": 1}\n```') == {"a": 1}

    def test_json_con_texto_alrededor(self):
        assert parse_json_loose('Claro, acá está:\n{"a": [1, 2]}\nEspero que sirva') == {"a": [1, 2]}


class TestChunking:
    def test_split_sections_respeta_limite(self):
        lines = [
            {"seq": index, "start_ms": index * 1000, "end_ms": index * 1000 + 900, "speaker": "Ana", "text": "palabra " * 50}
            for index in range(40)
        ]
        sections = _split_sections(lines, 3000)
        assert len(sections) > 1
        assert sum(len(section) for section in sections) == 40
        for section in sections:
            size = sum(len(line["text"]) + 30 for line in section)
            assert size <= 3000 + 500  # una línea puede exceder marginalmente

    def test_format_ms(self):
        assert format_ms(0) == "00:00"
        assert format_ms(65_000) == "01:05"
        assert format_ms(3_725_000) == "01:02:05"
        assert format_ms(None) == "--:--"


class TestClaimContext:
    LINES = [
        {"seq": 1, "start_ms": 0, "end_ms": 2000, "speaker": "Ana", "text": "Hola a todos, empecemos"},
        {"seq": 2, "start_ms": 2000, "end_ms": 5000, "speaker": "Marcos", "text": "El presupuesto quedó aprobado ayer"},
        {"seq": 3, "start_ms": 5000, "end_ms": 8000, "speaker": "Ana", "text": "Entonces el lanzamiento se mueve al viernes"},
    ]

    def test_encuentra_por_timestamp(self):
        context = _claim_context("algo cualquiera", 5000, self.LINES, window=1)
        assert any(line["seq"] == 3 for line in context)

    def test_encuentra_por_lexico(self):
        context = _claim_context("el presupuesto fue aprobado", None, self.LINES)
        assert any("presupuesto" in line["text"] for line in context)

    def test_sin_coincidencias(self):
        context = _claim_context("xyzabc", None, self.LINES)
        assert context == []
