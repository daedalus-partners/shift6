from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
import logging

from .api.v1.router import router as api_v1_router
from .api.v1.email.router import router as email_router
from .api.v1.coverage.router import router as coverage_router
from .api.v1.settings.router import router as settings_router
from .api.v1.tasks.router import router as tasks_router
from .routers_retrieval import router as retrieval_router

# Configure logging
# Default to DEBUG for dev (AUTH_MODE=none), INFO for prod
auth_mode = os.getenv("AUTH_MODE", "none")
log_level_env = os.getenv("LOG_LEVEL", "").upper()
if log_level_env:
    log_level = getattr(logging, log_level_env, logging.INFO)
elif auth_mode == "none":
    log_level = logging.DEBUG
else:
    log_level = logging.INFO

logging.basicConfig(
    level=log_level,
    format="%(levelname)-8s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

app = FastAPI(title="Shift6 Client Quote Generator API")
allowed_origins_env = os.getenv(
    "CORS_ALLOW_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost,http://127.0.0.1",
)
allowed_origins = allowed_origins_env.split(",") if allowed_origins_env else []

if auth_mode == "none":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in allowed_origins if origin.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_v1_router, prefix="")
app.include_router(email_router, prefix="/api/v1")
app.include_router(coverage_router, prefix="/api/v1")
app.include_router(settings_router, prefix="/api/v1")
app.include_router(tasks_router, prefix="/api/v1")
# Legacy retrieval endpoints used by tests
app.include_router(retrieval_router, prefix="")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"service": "shift6-api", "docs": "/docs"}
