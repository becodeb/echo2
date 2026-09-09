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
