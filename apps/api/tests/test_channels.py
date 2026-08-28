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
