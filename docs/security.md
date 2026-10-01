# Seguridad y privacidad en Echo

## Modelo de datos sensibles

| Dato | Tratamiento |
|---|---|
| Audio | **No queda guardado.** Copia de trabajo temporal por reunión (`RECORDINGS_DIR/<id>.pcm`) para separar hablantes con el audio completo; se borra al terminar el pipeline (`services/recording.finalize_recording`) y la limpieza periódica borra cualquier resto a las 24 h. Solo si la reunión se graba (opción explícita) se sube al Drive de quien grabó. Sin localStorage/IndexedDB de audio. |
| Transcript y derivados | PostgreSQL, aislados por organización |
| API keys de providers | Cifradas en reposo (Fernet/AES128-CBC+HMAC) con `ENCRYPTION_KEY`; al frontend solo vuelven enmascaradas (`sk-a…xyz`); excluidas de logs |
| Contraseñas | Argon2id |
| Refresh token de Google Drive | Uno por organización, cifrado en reposo con la misma `ENCRYPTION_KEY` (`OrgGoogleDrive.refresh_token_enc`). El access token se canjea en cada operación y vive solo en memoria. Scope mínimo `drive.file` |
| Google Login | **No persiste ningún token.** Pide `access_type=online` y guarda únicamente el `google_sub` en el usuario |
| Mi voz (biometría) | `user_voice_samples`: la muestra (WAV, hasta 10 s) y su huella (`sample_embedding`, `embedding`, 256 floats de WeSpeaker ResNet34). La graba la propia persona con consentimiento explícito; la huella se calcula en el servidor (`services/voiceprint.py`, ONNX en CPU), nunca sale a terceros. Se compara con la de cada persona que habló después de la pasada final; de quien no grabó su voz no se guarda ninguna huella. "Mejorar con mis reuniones" (§7.4) promedia la huella con reconocimientos seguros; apagarlo vuelve a la muestra. Borrar Mi voz o la cuenta borra todo. |


> `SpeakerProfile` (tabla `speaker_profiles`) sigue sin usarse: Mi voz vive
> en `user_voice_samples`.

## Autenticación y sesiones

- Access token JWT de 15 min (en memoria del cliente, nunca en cookies).
- Refresh token rotativo de 14 días en cookie `httpOnly` + `SameSite=Lax`
  con path restringido a `/api/auth`; cada refresh revoca el anterior
  (detección de replay). Logout revoca server-side.
- Anti-CSRF del refresh: exige el header custom `x-echo-client` (un form
  cross-site no puede añadir headers).
- WebSockets: access token corto por query param (el browser no permite
  headers en WS); en producción viaja por `wss`.

## Autorización (RBAC + tenant isolation)

- Roles de organización: owner > admin > member > viewer; roles por reunión
  compartida: admin/editor/commenter/viewer.
- **Regla de oro**: el `X-Organization-Id` del cliente jamás se usa sin
  verificar la membresía en DB (`get_org_context`). Toda query filtra por
  `organization_id` del contexto; las reuniones se cargan con
  `get_meeting_or_404` (404 para no filtrar existencia).
- Reuniones privadas: visibles solo para el creador, admins y usuarios con
  share explícito.
- Tests dedicados (`test_tenant_isolation.py`): header ajeno → 403, acceso
  directo → 404, edición/finish → 404, búsqueda y tareas sin fuga.

## Compartir

Links con token aleatorio (256 bits), rol limitado (viewer/commenter),
expiración opcional, revocación, contador de accesos y flag de descarga.
Accesos importantes al audit log.

## Superficie web

CORS restringido a `WEB_ORIGIN`; headers `X-Content-Type-Options`,
`X-Frame-Options: DENY`, `Referrer-Policy`, HSTS en producción; validación
Pydantic en todos los inputs; rate limiting en auth/chat/pairing; el markdown
del acta se renderiza con escape HTML propio (sin `innerHTML` de contenido
crudo).

## Echo Bridge

Bind exclusivo 127.0.0.1; pairing con validación de `Origin` contra
allowlist; tokens de sesión efímeros en memoria; rate limit; CORS
restringido. Una página maliciosa no puede alcanzar el motor local ni el
micrófono a través del bridge.

## Dispositivos

Token de 320 bits entregado solo durante el pairing (código de 6 dígitos,
TTL 10 min, un solo uso); en DB se guarda su hash SHA-256. Desvincular
invalida el token. El heartbeat expone únicamente estado operativo.

## Observabilidad

Logs estructurados con latencias de STT/LLM y errores de provider. **Nunca**
se loggean: audio, API keys, tokens, ni transcripts completos. Audit log por
organización para acciones sensibles (shares, aprobaciones, cambios de rol,
configuración de IA).
