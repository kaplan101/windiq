from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness: der Prozess läuft und beantwortet Anfragen."""
    return {"status": "ok"}
