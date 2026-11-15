"""FastAPI application entry point for the initial setup milestone."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.config import get_settings
from app.db.postgres import dispose_database, initialize_database
from app.api.routes import auth, bookings, rooms

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.database_url:
        initialize_database()
    yield
    dispose_database()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="API for the NITC CCC Terminal Booking Tracker.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.frontend_origin.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

for prefix in [settings.api_prefix, "/v1"]:
    app.include_router(auth.router, prefix=prefix)
    app.include_router(rooms.router, prefix=prefix)
    app.include_router(bookings.router, prefix=prefix)


@app.get("/", tags=["meta"])
@app.get("/api", tags=["meta"])
def root_check() -> dict[str, str]:
    return {"status": "ok", "name": settings.app_name, "version": "0.1.0"}


@app.get("/health", tags=["health"])
@app.get("/api/health", tags=["health"])
def health_check() -> dict[str, str]:
    """Return process liveness without exposing configuration or secrets."""
    return {"status": "ok"}


@app.get(f"{settings.api_prefix}/", tags=["meta"])
@app.get("/v1/", tags=["meta"])
def api_root() -> dict[str, str]:
    return {"name": settings.app_name, "version": "0.1.0"}
