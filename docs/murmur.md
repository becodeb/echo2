# Murmur como motor de Echo

Murmur es el motor STT local preferido de Echo. La integración vive en Echo
Bridge (`apps/bridge`), que **no asume cómo está instalado**: lo detecta en
runtime.

## Estado en esta máquina

Durante el desarrollo se buscó una instalación de Murmur en este equipo
(PATH, procesos, servicios de Windows y carpetas típicas) y **no se
encontró**. Por eso la integración quedó como autodetección + override
manual, y el modo cloud cubre mientras tanto.

## Cómo conectar tu Murmur

### Caso A — `murmur` está en el PATH

No hay que hacer nada: el bridge lo detecta al arrancar, sondea `murmur
--help` y elige el subcomando de transcripción (`transcribe`, `stt`,
`recognize`, `run` o archivo directo). `GET http://127.0.0.1:8974/health`
muestra `"engine": {"name": "murmur", "available": true}`.

### Caso B — instalación no estándar

Editá la config del bridge (`%APPDATA%\echo-bridge\config.json`):

```json
{
  "engine_command": "C:/ruta/a/murmur.exe transcribe {input}"
}
```

Placeholders disponibles:
- `{input}` — WAV mono 16 kHz temporal (se borra tras cada uso)
- `{lang}` — código de idioma de la reunión (`es`, `en`, …)
- `{output}` — base de salida si tu versión escribe archivos

El bridge lee la respuesta de dos formas:
1. **JSON estilo whisper.cpp** (si el comando incluye `-oj`): timestamps por
   segmento y speaker turns si el modelo los emite.
2. **Texto plano por stdout**: se toma como un segmento con la duración de la
   ventana.

### Caso C — Murmur expone un servicio HTTP

```json
{ "server_url": "http://127.0.0.1:PUERTO" }
```

Debe aceptar `POST /inference` multipart (`file`, `language`) y responder
`{"text": "..."}` — el formato de whisper.cpp server.

## Qué NO hace la integración

- No usa el portapapeles como transporte (prohibido por diseño).
- No guarda audio: el WAV temporal que exige un CLI vive milisegundos.
- No inventa capacidades: si Murmur no está, `/health` lo dice y la UI ofrece
  el modo cloud con su aviso de privacidad.
