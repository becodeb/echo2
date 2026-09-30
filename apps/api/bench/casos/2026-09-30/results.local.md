# Modelos locales / abiertos (30/9/2026, sin gastar OpenAI)

Medido contra reference.txt con metrics.py (números normalizados: "1, 2, 3" = "uno, dos, tres").

## Texto
| modelo | WER | frases de más | "uno dos tres probando" (5 reales) | inventadas | tiempo (135 s de audio, 12 hilos) |
|---|---|---|---|---|---|
| faster-whisper large-v3-turbo int8, language=es, VAD silero, sin contexto previo | 55% | 4 | 5 | 5 | 26 s |
| faster-whisper large-v3 int8, mismos parámetros | peor: se saltea "para la profe…", un tramo de 50 s | | | | 58 s |
| Parakeet TDT 0.6b v3 (base de Phonon-2), ONNX + VAD | cambia a inglés sobre el ruido ("Yeah", "What I'm") | | | | — |
| Phonon-2 | no probado: solo inglés según su model card | | | | — |
| gpt-4o-transcribe (mejor pre-procesado) | 72-93%, 1700% cuando entra en bucle (6/12 corridas) | 8-15 | 5-6 | 10-12 | API |

## Quién habló (acierto por tiempo)
| método | personas | acierto | A | B | C | D | E |
|---|---|---|---|---|---|---|---|
| pyannote-seg 3.0 + ERes2Net (3D-Speaker), k=5 | 5 | 49% | 47% | 83% | 58% | 7% | 0% |
| pyannote-seg 3.0 + WeSpeaker ResNet34, k=5 | 5 | 48% | 45% | 83% | 58% | 0% | 35% |
| pyannote-seg 3.0 + TitaNet large, k=5 | 5 | 37% | 39% | 83% | 28% | 0% | 0% |
| ECAPA (SpeechBrain) + clustering por ventanas, k=5 | 5 | 38% | 50% | 65% | 7% | 17% | 0% |
| gpt-4o-transcribe-diarize (9 corridas) | 2-4 | 32-46% | 43-62% | 60-77% | 0-36% | 0% | 0% |

Con umbral en vez de cantidad fija de personas, pyannote+WeSpeaker encuentra 1-3 personas (27-37%): saber cuántas son ayuda mucho.

Servidor de producción (Coolify): 2 vCPU Xeon E7-8880 v3 (2015), 4 GB de RAM (1,4 GB libres), carga promedio ~11, disco al 85%. No da para correr Whisper ni la separación de voces ahí.
