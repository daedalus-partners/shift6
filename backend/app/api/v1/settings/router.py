from fastapi import APIRouter

router = APIRouter(prefix="/settings", tags=["Settings"])

@router.get("/health")
def settings_health():
    return {"status": "coming_soon"}


