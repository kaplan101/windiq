from fastapi import FastAPI

from app.api.routers import health_router

app = FastAPI(title="WindIQ Ertragsrechnung")
app.include_router(health_router.router)
