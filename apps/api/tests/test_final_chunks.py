"""Pasada final por tramos (services/final_chunks.py): unir personas y no repetir el solapamiento."""
from echo_api.services.final_chunks import CHUNK_MS, OVERLAP_MS, Chunk, bounds, chunk_count, stitch_segments, stitch_words
from echo_api.services.stt.base import SttSegment, SttWord


def _words(start: int, text: str, speaker: str, step: int = 400) -> list[SttWord]:
    return [SttWord(word, start + i * step, start + i * step + 300, speaker) for i, word in enumerate(text.split())]


def test_tramos_de_cinco_minutos_con_solapamiento():
    assert chunk_count(1) == 1 and chunk_count(CHUNK_MS) == 1 and chunk_count(CHUNK_MS + 1) == 2
    assert bounds(0, 61 * 60_000) == (0, CHUNK_MS)
    assert bounds(1, 61 * 60_000) == (CHUNK_MS - OVERLAP_MS, 2 * CHUNK_MS)
    assert bounds(12, 61 * 60_000) == (12 * CHUNK_MS - OVERLAP_MS, 61 * 60_000)


def test_las_personas_se_unen_por_el_solapamiento():
    boundary = CHUNK_MS
    start = boundary - OVERLAP_MS
    # Tramo 1: la mamá es speaker_0 y la docente speaker_1. Las dos hablan en el solapamiento.
    first = (
        _words(0, "buenas tardes gracias por venir", "speaker_1")
        + _words(start + 1_000, "mi hijo no quiere ir a la escuela los lunes", "speaker_0")
        + _words(start + 15_000, "entiendo vamos a hablar con la maestra integradora", "speaker_1")
    )
    # Tramo 2: ElevenLabs las numera al revés.
    second = (
        _words(start + 1_000, "mi hijo no quiere ir a la escuela los lunes", "speaker_1")
        + _words(start + 15_000, "entiendo vamos a hablar con la maestra integradora", "speaker_0")
        + _words(boundary + 10_000, "perfecto nos vemos el viernes", "speaker_1")
        + _words(boundary + 20_000, "hola soy la directora", "speaker_2")
    )
    chunks = [
        Chunk(0, 0, boundary, "elevenlabs", "es", first, [], []),
        Chunk(1, start, 2 * boundary, "elevenlabs", "es", second, [], []),
    ]
    words = stitch_words(chunks)
    by_text = {}
    for word in words:
        by_text.setdefault(word.speaker, []).append(word.text)
    text_of = {speaker: " ".join(ws) for speaker, ws in by_text.items()}
    mama = next(s for s, t in text_of.items() if "hijo" in t)
    docente = next(s for s, t in text_of.items() if "buenas" in t)
    # La mamá sigue siendo la misma persona en el tramo nuevo, y la docente también.
    assert "perfecto nos vemos el viernes" in text_of[mama]
    assert "integradora" in text_of[docente]
    assert mama != docente
    # Quien no habló en el solapamiento es una persona nueva.
    directora = next(s for s, t in text_of.items() if "directora" in t)
    assert directora not in (mama, docente)
    # El solapamiento no se repite.
    assert sum(1 for w in words if w.text == "lunes") == 1
    assert sum(1 for w in words if w.text == "integradora") == 1
    assert [w.start_ms for w in words] == sorted(w.start_ms for w in words)


def test_sin_coincidencias_no_se_inventa_quien_es():
    boundary = CHUNK_MS
    start = boundary - OVERLAP_MS
    chunks = [
        Chunk(0, 0, boundary, "elevenlabs", "es", _words(0, "hola qué tal", "speaker_0"), [], []),
        Chunk(1, start, 2 * boundary, "elevenlabs", "es", _words(boundary + 5_000, "otra cosa distinta", "speaker_0"), [], []),
    ]
    speakers = {w.speaker for w in stitch_words(chunks)}
    assert len(speakers) == 2  # sin palabras en común no se asume que es la misma persona


def test_frases_sin_personas_sin_repetir():
    boundary = CHUNK_MS
    start = boundary - OVERLAP_MS
    first = [SttSegment("uno", 1_000, 2_000), SttSegment("en el solapamiento", start + 5_000, start + 7_000)]
    second = [
        SttSegment("en el solapamiento", start + 5_000, start + 7_000),
        SttSegment("después del corte", start + 30_000, start + 32_000),
        SttSegment("dos", boundary + 1_000, boundary + 2_000),
    ]
    chunks = [Chunk(0, 0, boundary, "groq", "es", [], first, []), Chunk(1, start, 2 * boundary, "groq", "es", [], second, [])]
    assert [s.text for s in stitch_segments(chunks)] == ["uno", "en el solapamiento", "después del corte", "dos"]
