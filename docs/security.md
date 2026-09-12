# Seguridad y privacidad en Echo

## Modelo de datos sensibles

| Dato | Tratamiento |
|---|---|
| Audio | **Nunca persiste.** RAM → STT → descarte. Temporales de CLI/ffmpeg borrados en `finally`. Sin localStorage/IndexedDB de audio. |
| Transcript y derivados | PostgreSQL, aislados por organización |
| API keys de providers | Cifradas en reposo (Fernet/AES128-CBC+HMAC) con `ENCRYPTION_KEY`; al frontend solo vuelven enmascaradas (`sk-a…xyz`); excluidas de logs |
| Contraseñas | Argon2id |
| Refresh token de Google Drive | Uno por organización, cifrado en reposo con la misma `ENCRYPTION_KEY` (`OrgGoogleDrive.refresh_token_enc`). El access token se canjea en cada operación y vive solo en memoria. Scope mínimo `drive.file` |
| Google Login | **No persiste ningún token.** Pide `access_type=online` y guarda únicamente el `google_sub` en el usuario |

> **Voice profiles: no están en esta tabla a propósito.** El modelo
> `SpeakerProfile` (embedding de voz + `consent_at`) existe en
> `models/meetings.py` y la migración crea la tabla, pero **ningún código la
> lee ni la escribe**: no hay endpoint para dar de alta un perfil ni nada que
> calcule ese embedding. Es una tabla vacía. Listarla como dato sensible
> tratado sería describir una feature que no existe — y de paso sugerir que
> Echo guarda biometría de voz, cosa que hoy no hace. Si algún día se
> implementa, vuelve a la tabla con su fila.

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
