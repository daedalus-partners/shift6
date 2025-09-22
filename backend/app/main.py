from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

from .api.v1.router import router as api_v1_router
from .api.v1.email.router import router as email_router
from .api.v1.coverage.router import router as coverage_router
from .api.v1.settings.router import router as settings_router

app = FastAPI(title="Shift6 Client Quote Generator API")

auth_mode = os.getenv("AUTH_MODE", "none")
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


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"service": "shift6-api", "docs": "/docs"}
