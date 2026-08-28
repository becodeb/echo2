# Murmur como motor de Echo

**Estado: INSTALADO Y FUNCIONANDO.** Tu Murmur
(`Downloads/murmur-youtube-main`) es una app de dictado cuyo motor en Windows
es **NVIDIA Parakeet TDT 0.6B via sherpa-onnx** — y ese motor es exactamente
lo que Echo Bridge usa ahora, de forma directa, 100% local y offline.

## Qué quedó instalado

```
%LOCALAPPDATA%/echo-bridge/
|-- sherpa/bin/sherpa-onnx-offline.exe     (sherpa-onnx v1.13.5, ~20 MB)
`-- sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8/
    |-- encoder.int8.onnx   (~652 MB)
    |-- decoder.int8.onnx
    |-- joiner.int8.onnx
    `-- tokens.txt          (v3 multilingue: espanol + ingles + 23 mas)
```

- Modelo **v3 multilingüe** (el repo de Murmur usa v2 solo-inglés por
  default; v3 era necesario para reuniones en español).
- ~16× más rápido que tiempo real en CPU (RTF ≈ 0.06 con 4 threads).
- Licencias: modelo CC-BY-4.0, sherpa-onnx Apache-2.0.

El bridge lo autodetecta al arrancar (paso 3 de la detección) y `/health`
reporta `"name": "Parakeet (sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8)"`.
Verificado end-to-end: PCM por WebSocket → VAD → Parakeet → texto con
timestamps, en español y en inglés.

## Detección del bridge (orden completo)

1. `engine_command` de la config (override manual para cualquier CLI).
2. `murmur` en PATH (sondea subcomandos vía `--help`).
3. **sherpa-onnx + Parakeet** en `%LOCALAPPDATA%/echo-bridge/` (lo instalado).
4. whisper.cpp CLI + modelo ggml/gguf.
5. Servidor HTTP local compatible whisper.cpp server (`server_url`).

## Limitación conocida

En modo CLI el modelo se carga en cada utterance (~2 s de overhead sobre los
~0.3 s de inferencia). Latencia total por frase: ~2.5 s. Mejora prevista:
usar `sherpa-onnx-offline-websocket-server.exe` (incluido en el paquete) como
proceso persistente — el modelo queda cargado y la latencia baja al RTF puro.

## Si algún día querés otro motor

- La app de dictado Murmur compilada: agregá su exe al PATH o usá
  `engine_command`.
- whisper.cpp: dejá un modelo ggml en `~/whisper.cpp/models` y borrá la
  carpeta sherpa (o priorizá con `engine_command`).
