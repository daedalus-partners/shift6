from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

from .routers_clients import router as clients_router
from .routers_knowledge import router as knowledge_router
from .routers_style import router as styles_router
from .routers_samples import router as samples_router
from .routers_retrieval import router as retrieval_router
from .routers_generate import router as generate_router

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

app.include_router(clients_router)
app.include_router(knowledge_router)
app.include_router(styles_router)
app.include_router(samples_router)
app.include_router(retrieval_router)
app.include_router(generate_router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"service": "shift6-api", "docs": "/docs"}
