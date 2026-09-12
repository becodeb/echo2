"""Echo API — aplicación FastAPI.

"The meeting ends. Echo remembers."
"""
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
log = logging.getLogger("echo")

settings = get_settings()

app = FastAPI(
    title="Echo API",
    version="0.1.0",
    docs_url="/api/docs" if not settings.is_production else None,
    openapi_url="/api/openapi.json" if not settings.is_production else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "echo-api"}


# Routers
from .routers import auth  # noqa: E402

app.include_router(auth.router)


def _include_optional_routers() -> None:
    """Routers que se agregan a medida que se implementan."""
    from importlib import import_module

    for name in (
        "auth_google",
        "admin",
        "families",
        "attachments",
        "drive",
        "reports",
        "orgs",
        "meetings",
        "live",
        "transcript",
        "insights",
        "minutes",
        "chat",
        "projects",
        "tasks",
        "people",
        "search",
        "devices",
        "device_stream",
        "settings_ai",
        "sharing",
        "comments",
        "notifications",
        "imports",
        "exports",
        "memory",
    ):
        try:
            module = import_module(f".routers.{name}", package="echo_api")
        except ModuleNotFoundError:
            continue
        app.include_router(module.router)


_include_optional_routers()


@app.on_event("startup")
async def _sync_superadmins() -> None:
    """Aplica SUPERADMIN_EMAILS sobre los usuarios existentes.

    Va acá y no en la app para que nadie se ascienda solo: se cambia la
    variable de entorno y se reinicia. Si el usuario todavía no se registró,
    queda marcado en el próximo arranque.

    Nunca puede impedir que la API levante: si esto falla, se loguea y sigue.
    """
    emails = settings.superadmin_email_list
    if not emails:
        return
    try:
        from sqlalchemy import select, update

        from .db import SessionLocal
        from .models import User

        async with SessionLocal() as db:
            await db.execute(update(User).where(User.email.in_(emails)).values(is_superadmin=True))
            # Quien deja de estar en la lista pierde el privilegio.
            await db.execute(
                update(User)
                .where(User.is_superadmin.is_(True), User.email.notin_(emails))
                .values(is_superadmin=False)
            )
            await db.commit()
            found = (
                (await db.execute(select(User.email).where(User.email.in_(emails)))).scalars().all()
            )
        log.info("superadmins activos: %s", ", ".join(sorted(found)) or "ninguno")
        faltan = sorted(set(emails) - set(found))
        if faltan:
            log.info("superadmins declarados sin cuenta todavía: %s", ", ".join(faltan))
    except Exception:
        log.exception("no se pudo sincronizar la lista de superadmins")


# Cuánto puede llevar un trabajo antes de darlo por muerto.
#
# El número está del lado generoso a propósito. Un pipeline post-reunión con un
# transcript largo y un LLM lento (resumen jerárquico + verificación de citas,
# reintentos incluidos) puede tardar bastante; y sobre todo: este hook corre al
# arrancar, o sea que puede haber OTRA instancia de la API viva procesando esa
# misma reunión mientras ésta levanta. Con un umbral corto le mataríamos
# trabajo en curso a un proceso sano. 3 horas es varias veces el peor caso
# medido y sigue siendo infinitamente menos que "para siempre", que es lo que
# pasa hoy cuando nadie limpia estos estados.
STALE_JOB_HOURS = 3

_STALE_MINUTES_MESSAGE = (
    "La generación quedó interrumpida (probablemente el servidor se reinició en el medio). "
    "No se perdió nada del contenido de la reunión: tocá «Regenerar» para volver a intentarlo."
)
_STALE_MEETING_MESSAGE = (
    "El procesamiento quedó interrumpido (probablemente el servidor se reinició en el medio). "
    "La transcripción está guardada; se puede volver a procesar la reunión."
)


@app.on_event("startup")
async def _fail_stale_jobs() -> None:
    """Cierra los trabajos que quedaron colgados por un reinicio.

    "generating" y "processing" son estados que sólo termina la tarea que los
    empezó. Si la API se cae en el medio, no queda nadie que los toque nunca
    más: el acta se queda en "generando" y la UI le hace polling cada 3
    segundos hasta el fin de los tiempos (MeetingDetail.tsx), y la reunión se
    queda en "processing", que es justo el estado que `finish_meeting` rechaza
    con 409 — o sea que desde la interfaz no hay forma de recuperarla.

    Nunca puede impedir que la API levante: si esto falla, se loguea y sigue.
    """
    try:
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import or_, update

        from .db import SessionLocal
        from .models import Meeting, Minutes

        cutoff = datetime.now(UTC) - timedelta(hours=STALE_JOB_HOURS)
        async with SessionLocal() as db:
            stale_minutes = await db.execute(
                update(Minutes)
                .where(
                    Minutes.generation_status == "generating",
                    # generation_started_at se escribía en dos lugares y no lo
                    # leía nadie: existe exactamente para esto. NULL cuenta como
                    # vencido — un "generating" sin fecha de arranque es de una
                    # fila vieja y no hay forma de saber si sigue viva, y
                    # dejarla colgada es peor que pedir un reintento.
                    or_(
                        Minutes.generation_started_at < cutoff,
                        Minutes.generation_started_at.is_(None),
                    ),
                )
                .values(generation_status="failed", generation_error=_STALE_MINUTES_MESSAGE)
            )
            stale_meetings = await db.execute(
                update(Meeting)
                .where(
                    Meeting.status == "processing",
                    # Meeting no tiene un `processing_started_at`. Se usa
                    # updated_at (TimestampMixin) y no ended_at justamente
                    # porque NO es fijo: el pipeline reescribe processing_state
                    # en cada etapa (pipeline._set_stage), así que mientras algo
                    # avance el reloj se corre solo y el trabajo vivo queda a
                    # salvo. Si el proceso murió, nadie lo vuelve a tocar y la
                    # fila envejece sola hasta vencer.
                    Meeting.updated_at < cutoff,
                )
                .values(
                    status="failed",
                    processing_state={"stage": "failed", "error": _STALE_MEETING_MESSAGE},
                )
            )
            await db.commit()
        if stale_minutes.rowcount or stale_meetings.rowcount:
            log.info(
                "trabajos vencidos cerrados al arrancar: %s actas, %s reuniones",
                stale_minutes.rowcount,
                stale_meetings.rowcount,
            )
    except Exception:
        log.exception("no se pudieron cerrar los trabajos colgados")
