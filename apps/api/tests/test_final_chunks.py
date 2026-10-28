"""Pasada final por tramos (services/final_chunks.py): cortes en silencio, unir personas por la voz."""
import uuid

import numpy as np
import pytest

from echo_api.services import final_chunks as fc
from echo_api.services.final_chunks import CHUNK_MS, OVERLAP_MS, Chunk, link_voices, spans, stitch_segments, stitch_words
from echo_api.services.stt.base import SttSegment, SttWord


def _words(start: int, text: str, speaker: str, step: int = 400) -> list[SttWord]:
    return [SttWord(word, start + i * step, start + i * step + 300, speaker) for i, word in enumerate(text.split())]


def _voice(seed: int, noise: float = 0.0, ms: int = 15000, rng=None) -> dict:
    base = np.random.default_rng(seed).normal(size=256)
    if noise:
        base = base + (rng or np.random.default_rng(seed + 1000)).normal(size=256) * noise
    return {"vector": list(base / np.linalg.norm(base)), "ms": ms}


def _chunk(index: int, start: int, end: int, words: list[SttWord], voices: dict) -> Chunk:
    return Chunk(index, start, end, "elevenlabs", "es", words, [], [], voices)


def _speakers_by_text(words: list[SttWord]) -> dict[str, str]:
    out: dict[str, list[str]] = {}
    for word in words:
        out.setdefault(word.speaker, []).append(word.text)
    return {speaker: " ".join(texts) for speaker, texts in out.items()}


def test_el_corte_cae_en_el_silencio():
    rng = np.random.default_rng(1)
    audio = (rng.normal(size=16000 * 30) * 3000).astype(np.int16)
    audio[16000 * 12:16000 * 13] = 0  # un segundo de silencio entre los 12 y 13 s
    cut = fc.quiet_point(audio.tobytes(), 60_000)
    assert 72_000 <= cut <= 73_000


def test_tramos_sin_repetir_audio_y_respaldo_con_solapamiento():
    plan = {"mode": "voice", "cuts": [298_000, 597_500]}
    assert spans(plan, 700_000) == [(0, 298_000), (298_000, 597_500), (597_500, 700_000)]
    old = {"mode": "overlap", "cuts": [CHUNK_MS, 2 * CHUNK_MS]}
    assert spans(old, 700_000)[1] == (CHUNK_MS - OVERLAP_MS, 2 * CHUNK_MS)


def test_los_cortes_se_deciden_cada_cinco_minutos_y_el_resto_va_al_ultimo(tmp_path, monkeypatch):
    monkeypatch.setattr(fc, "chunks_dir", lambda meeting_id: tmp_path / "chunks")
    monkeypatch.setattr(fc.voiceprint, "available", lambda: True)
    audio = (np.random.default_rng(2).normal(size=16000 * 60 * 12) * 3000).astype(np.int16)
    audio[16000 * 290:16000 * 291] = 0
    path = tmp_path / "audio.pcm"
    path.write_bytes(audio.tobytes())
    meeting = uuid.uuid4()
    plan = fc.extend_plan(meeting, path, 7 * 60_000, final=False)
    assert plan["mode"] == "voice"
    assert len(plan["cuts"]) == 1 and 290_000 <= plan["cuts"][0] <= 291_000
    # Al finalizar a los 11 min: un corte más, y lo que queda (≤ 6 min) es el último tramo.
    plan = fc.extend_plan(meeting, path, 11 * 60_000, final=True)
    assert len(plan["cuts"]) == 2
    assert 11 * 60_000 - plan["cuts"][-1] <= CHUNK_MS + fc.TAIL_SLACK_MS
    # Lo decidido queda guardado: no cambia al volver a pedirlo.
    assert fc.load_plan(meeting)["cuts"] == plan["cuts"]


def test_las_personas_se_unen_por_la_voz_aunque_elevenlabs_las_numere_distinto():
    rng = np.random.default_rng(7)
    mama, docente, directora = 1, 2, 3
    chunks = [
        _chunk(0, 0, CHUNK_MS, _words(0, "buenas tardes gracias por venir", "speaker_1")
               + _words(10_000, "mi hijo no quiere ir a la escuela", "speaker_2"),
               {"speaker_1": _voice(docente, 0.4, rng=rng), "speaker_2": _voice(mama, 0.4, rng=rng)}),
        # La mamá no habla en el segundo tramo.
        _chunk(1, CHUNK_MS, 2 * CHUNK_MS, _words(CHUNK_MS + 1_000, "vamos a hablar con la integradora", "speaker_1")
               + _words(CHUNK_MS + 20_000, "hola soy la directora", "speaker_2"),
               {"speaker_1": _voice(docente, 0.4, rng=rng), "speaker_2": _voice(directora, 0.4, rng=rng)}),
        # Vuelve en el tercero, con otro número.
        _chunk(2, 2 * CHUNK_MS, 3 * CHUNK_MS, _words(2 * CHUNK_MS + 1_000, "perfecto nos vemos el viernes", "speaker_1")
               + _words(2 * CHUNK_MS + 9_000, "gracias a ustedes", "speaker_2"),
               {"speaker_1": _voice(mama, 0.4, rng=rng), "speaker_2": _voice(docente, 0.4, rng=rng)}),
    ]
    words, prints = stitch_words(chunks)
    text_of = _speakers_by_text(words)
    assert len(text_of) == 3
    who = {next(s for s, t in text_of.items() if phrase in t): phrase for phrase in ("hijo", "buenas", "directora")}
    assert len(who) == 3
    mama_label = next(s for s, t in text_of.items() if "hijo" in t)
    docente_label = next(s for s, t in text_of.items() if "buenas" in t)
    assert "viernes" in text_of[mama_label]
    assert "integradora" in text_of[docente_label] and "ustedes" in text_of[docente_label]
    assert set(prints) == set(text_of)
    assert [w.start_ms for w in words] == sorted(w.start_ms for w in words)


def test_dos_personas_del_mismo_tramo_nunca_quedan_como_una():
    # Aunque ElevenLabs las haya separado y se parezcan mucho.
    chunks = [_chunk(0, 0, CHUNK_MS, _words(0, "hola", "speaker_1") + _words(5_000, "chau", "speaker_2"),
                     {"speaker_1": _voice(1, 0.05), "speaker_2": _voice(1, 0.05, rng=np.random.default_rng(99))})]
    mappings, _ = link_voices(chunks)
    assert mappings[0]["speaker_1"] != mappings[0]["speaker_2"]


def test_una_voz_distinta_es_otra_persona_y_sin_huella_no_se_adivina():
    chunks = [
        _chunk(0, 0, CHUNK_MS, _words(0, "hola qué tal", "speaker_1"), {"speaker_1": _voice(1)}),
        _chunk(1, CHUNK_MS, 2 * CHUNK_MS, _words(CHUNK_MS + 5_000, "otra cosa", "speaker_1")
               + _words(CHUNK_MS + 9_000, "sí", "speaker_2"),
               {"speaker_1": _voice(2)}),
    ]
    mappings, _ = link_voices(chunks)
    assert mappings[1]["speaker_1"] != mappings[0]["speaker_1"]
    assert mappings[1]["speaker_2"] not in (mappings[0]["speaker_1"], mappings[1]["speaker_1"])


def test_respaldo_sin_modelo_de_voz_une_por_el_solapamiento():
    boundary = CHUNK_MS
    start = boundary - OVERLAP_MS
    first = (
        _words(0, "buenas tardes gracias por venir", "speaker_1")
        + _words(start + 1_000, "mi hijo no quiere ir a la escuela los lunes", "speaker_0")
    )
    second = (
        _words(start + 1_000, "mi hijo no quiere ir a la escuela los lunes", "speaker_1")
        + _words(boundary + 10_000, "perfecto nos vemos el viernes", "speaker_1")
    )
    chunks = [_chunk(0, 0, boundary, first, {}), _chunk(1, start, 2 * boundary, second, {})]
    words, prints = stitch_words(chunks, "overlap")
    text_of = _speakers_by_text(words)
    mama = next(s for s, t in text_of.items() if "hijo" in t)
    assert "viernes" in text_of[mama]
    assert sum(1 for w in words if w.text == "lunes") == 1
    assert prints == {}


def test_frases_sin_personas_sin_repetir():
    first = [SttSegment("uno", 1_000, 2_000), SttSegment("antes del corte", CHUNK_MS - 5_000, CHUNK_MS - 3_000)]
    second = [SttSegment("después del corte", CHUNK_MS + 1_000, CHUNK_MS + 2_000)]
    chunks = [Chunk(0, 0, CHUNK_MS, "groq", "es", [], first, []), Chunk(1, CHUNK_MS, 2 * CHUNK_MS, "groq", "es", [], second, [])]
    assert [s.text for s in stitch_segments(chunks)] == ["uno", "antes del corte", "después del corte"]


@pytest.mark.parametrize("ms", [2000, 15000])
def test_la_huella_de_cada_persona_del_tramo(ms, monkeypatch):
    calls = []

    def fake_embed(samples):
        calls.append(len(samples))
        return np.ones(256, dtype=np.float32) / 16

    monkeypatch.setattr(fc.voiceprint, "embed", fake_embed)
    words = _words(0, " ".join(["palabra"] * (ms // 400)), "speaker_1") + _words(ms + 2_000, "otra persona habla un rato largo", "speaker_2")
    pcm = (np.zeros(16000 * 60)).astype(np.int16).tobytes()
    voices = fc.chunk_voices(pcm, words)
    # Una sola huella por persona, con hasta 15 s de su voz.
    assert len(calls) == len(voices)
    assert all(v["ms"] <= fc.VOICE_MS for v in voices.values())
    assert "speaker_1" in voices
