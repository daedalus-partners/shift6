from fastapi import APIRouter

# Quotes domain (re-exported existing routers)
from .quotes.clients import router as quotes_clients
from .quotes.knowledge import router as quotes_knowledge
from .quotes.styles import router as quotes_styles
from .quotes.samples import router as quotes_samples
from .quotes.chat import router as quotes_chat
from .quotes.generate import router as quotes_generate
from .quotes.prompts import router as quotes_prompts

router = APIRouter()

# Keep existing paths as-is to avoid breaking the frontend/tests
router.include_router(quotes_clients)
router.include_router(quotes_knowledge)
router.include_router(quotes_styles)
router.include_router(quotes_samples)
router.include_router(quotes_chat)
router.include_router(quotes_generate)
router.include_router(quotes_prompts)


