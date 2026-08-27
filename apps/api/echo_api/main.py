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
