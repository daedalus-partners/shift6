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

allowed_origins = os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:5173").split(",")

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
