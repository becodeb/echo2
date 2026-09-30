"""Atribución de hablante por canal y filtro de alucinaciones de Whisper."""
import array
import math

from echo_api.services.stt.channels import (
    MIC_SPEAKER,
    SYSTEM_SPEAKER,
    attribute_speaker,
    downmix,
    is_hallucination,
    is_silent,
    rms,
    split_channels,
)

SAMPLE_RATE = 16000


def tone(duration_ms: int, amplitude: int, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Seno de 440 Hz como voz sintética."""
    count = int(sample_rate * duration_ms / 1000)
    samples = array.array(
        "h",
        (int(amplitude * math.sin(2 * math.pi * 440 * i / sample_rate)) for i in range(count)),
    )
    return samples.tobytes()


def silence(duration_ms: int, sample_rate: int = SAMPLE_RATE) -> bytes:
    return array.array("h", (0,) * int(sample_rate * duration_ms / 1000)).tobytes()


def interleave(left: bytes, right: bytes) -> bytes:
    a = array.array("h")
    a.frombytes(left)
    b = array.array("h")
    b.frombytes(right)
    out = array.array("h")
    for index in range(min(len(a), len(b))):
        out.append(a[index])
        out.append(b[index])
    return out.tobytes()


class TestSplitChannels:
    def test_separa_intercalado(self):
        left, right = split_channels(interleave(tone(100, 8000), silence(100)))
        assert rms(left) > 1000
        assert rms(right) == 0

    def test_downmix_promedia(self):
        mixed = downmix(tone(100, 8000), silence(100))
        # promediar con silencio deja la mitad de la energía
        assert 0.4 < rms(mixed) / rms(tone(100, 8000)) < 0.6


class TestAtribucionDeHablante:
    def test_habla_el_microfono(self):
        mic, system = tone(500, 9000), silence(500)
        assert attribute_speaker(mic, system, 0, 500, SAMPLE_RATE) == MIC_SPEAKER

    def test_habla_el_sistema(self):
        # el caso de Discord: el remoto entra por el audio del sistema
        mic, system = silence(500), tone(500, 9000)
        assert attribute_speaker(mic, system, 0, 500, SAMPLE_RATE) == SYSTEM_SPEAKER

    def test_ambos_callados_no_atribuye(self):
        assert attribute_speaker(silence(500), silence(500), 0, 500, SAMPLE_RATE) is None

    def test_niveles_parecidos_no_arriesga(self):
        # diafonía: el parlante entra al micrófono con nivel similar
        mic, system = tone(500, 8000), tone(500, 7000)
        assert attribute_speaker(mic, system, 0, 500, SAMPLE_RATE) is None

    def test_ventana_acotada_al_segmento(self):
        # el micrófono habla en el primer medio segundo, el sistema en el segundo
        mic = tone(500, 9000) + silence(500)
        system = silence(500) + tone(500, 9000)
        assert attribute_speaker(mic, system, 0, 500, SAMPLE_RATE) == MIC_SPEAKER
        assert attribute_speaker(mic, system, 500, 1000, SAMPLE_RATE) == SYSTEM_SPEAKER


class TestSilencio:
    def test_silencio_detectado(self):
        assert is_silent(silence(1000), SAMPLE_RATE) is True

    def test_habla_no_es_silencio(self):
        assert is_silent(tone(1000, 9000), SAMPLE_RATE) is False


class TestAlucinaciones:
    def test_creditos_de_amara(self):
        assert is_hallucination("Subtítulos realizados por la comunidad de Amara.org") is True

    def test_variantes_de_subtitulado(self):
        assert is_hallucination("¡Gracias por ver el video!") is True
        assert is_hallucination("Subtitulado por la comunidad") is True

    def test_texto_vacio(self):
        assert is_hallucination("   ") is True

    def test_habla_real_pasa(self):
        assert is_hallucination("No sé para qué tiene dos micrófonos") is False
        assert is_hallucination("El presupuesto de compras quedó aprobado") is False


# ── Alucinaciones (banco del 30/9) ───────────────────────────────


def test_a_loop_of_the_model_is_left_once():
    from echo_api.services.stt.channels import strip_hallucinations

    # gpt-4o-transcribe con el audio entero: "¿Cómo estás?" x100.
    assert strip_hallucinations(" ".join(["¿Cómo estás?"] * 100) + " Bien, ¿y vos?") == "¿Cómo estás? Bien, ¿y vos?"
    # Alguien probando el micrófono lo dice 5 veces: eso se dijo, queda.
    said = " ".join(["Uno dos tres probando."] * 5)
    assert strip_hallucinations(said) == said


def test_lone_amen_dashes_and_english_fillers_are_not_speech():
    from echo_api.services.stt.channels import strip_hallucinations

    assert strip_hallucinations("Amén.") == ""
    assert strip_hallucinations("- -") == ""
    assert strip_hallucinations("Thank you.") == ""
    assert strip_hallucinations("¡Suscríbete al canal!") == ""
    # El guion de diálogo de subtítulos se saca, lo dicho queda.
    assert strip_hallucinations("- Hola, ¿cómo estás? - Bien.") == "Hola, ¿cómo estás? Bien."
    # Dentro de una frase real no se toca.
    assert strip_hallucinations("Rezamos y dijimos amén con los chicos.") == "Rezamos y dijimos amén con los chicos."


def test_whisper_signals_flag_invented_text():
    from echo_api.services.stt.base import SttSegment
    from echo_api.services.stt.channels import is_unreliable

    def seg(no_speech, logprob):
        return SttSegment("Gracias.", 0, 1000, no_speech_prob=no_speech, avg_logprob=logprob)

    assert is_unreliable(seg(0.9, -1.2)) is True  # silencio que el modelo completó
    assert is_unreliable(seg(0.9, -0.3)) is False  # dudó, pero lo oyó claro
    assert is_unreliable(seg(0.1, -1.8)) is True  # ruido puro
    assert is_unreliable(seg(0.1, -0.4)) is False
    assert is_unreliable(SttSegment("Hola.", 0, 1000)) is False  # motor sin señales


def test_groq_segments_carry_the_signals(monkeypatch):
    import asyncio

    import httpx

    from echo_api.services.stt.base import get_stt_provider

    class Reply:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, **kwargs):
            body = {"segments": [{"start": 0, "end": 1.2, "text": " Amén.", "no_speech_prob": 0.8,
                                  "avg_logprob": -1.3, "compression_ratio": 0.6}]}
            return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "AsyncClient", Reply)
    result = asyncio.run(get_stt_provider("groq", "k").transcribe_chunk(bytes(3200), 16000, "es"))
    [segment] = result.segments
    assert (segment.no_speech_prob, segment.avg_logprob, segment.compression_ratio) == (0.8, -1.3, 0.6)
