import logging
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routers import health_router, status_router, yield_router
from app.core.config import get_settings
from app.services.ingestion_service import run_sync
from app.services.sync_scheduler import SyncScheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# Jede einzelne HTTP-Anfrage zu loggen ist zu viel; Fehler und Retries loggt unser Client selbst
logging.getLogger("httpx").setLevel(logging.WARNING)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.sync_enabled:
        app.state.scheduler = SyncScheduler(run_sync, timedelta(minutes=settings.sync_interval_minutes))
        app.state.scheduler.start()
    yield
    if app.state.scheduler is not None:
        app.state.scheduler.stop()


app = FastAPI(title="WindIQ Ertragsrechnung", lifespan=lifespan)
app.state.scheduler = None
app.include_router(health_router.router)
app.include_router(status_router.router)
app.include_router(yield_router.router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
