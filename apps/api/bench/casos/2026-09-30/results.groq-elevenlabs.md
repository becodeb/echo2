# Groq y ElevenLabs con el código nuevo (30/9/2026, keys de prueba, sin OpenAI)

`python bench/stt_bench.py --case bench/casos/<caso> --audio "<mp3>" --out results.groq-elevenlabs.json`

## 30/9 (2:15, 5 personas; la referencia no tiene el tramo 0:26-1:47, por eso el WER alto y las "inventadas")
| variante | WER | frases de más | "uno dos tres probando" (5 reales) | personas | persona ok (palabras / turnos / tiempo) | turnos sin persona |
|---|---|---|---|---|---|---|
| lo que salió en producción | 209% | 30 | 27 | 2 | 58% / 29% / 47% | 3 (46% de las palabras) |
| prod_live (Groq sin pista) | 110% | 10 | 3 | — | — | borrador, se reemplaza |
| prod_final sin personas (Groq) | 71% | 4 | 5 | — | — | — |
| prod_final (Scribe v2) | 78% | 11 | 6 | 3 | 86% / 79% / 41% | 0 |

## 27/9 (20 s, 3 personas; referencia en borrador)
| variante | frases de más | personas | turnos sin persona |
|---|---|---|---|
| prod_final (Scribe v2) | 2 | 3 (Bautista, Vanina x2, el Choto: sin errores) | 0 |
| prod_final sin personas (Groq) | 2 | — | — |

Groq gratis: 20 pedidos por minuto. El en vivo de UNA reunión (un tramo cada 4-12 s)
ya lo toca; los proveedores ahora esperan lo que pide el 429 y reintentan
(services/stt/base.py), pero con más de una reunión a la vez hace falta el plan pago.
Groq devuelve siempre `no_speech_prob = 0`: la señal útil es `avg_logprob`.
