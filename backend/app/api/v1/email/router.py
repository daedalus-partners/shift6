from fastapi import APIRouter

router = APIRouter(prefix="/email", tags=["Email"])

@router.get("/health")
def email_health():
    return {"status": "coming_soon"}


