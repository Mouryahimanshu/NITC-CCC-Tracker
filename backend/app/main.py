"""FastAPI application entry point for the initial setup milestone."""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

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
    redirect_slashes=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.frontend_origin.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def vercel_path_rewrite_middleware(request: Request, call_next):
    """Normalize Vercel serverless function paths so routes always resolve."""
    matched = request.headers.get("x-matched-path")
    if matched and not matched.endswith("index.py"):
        request.scope["path"] = matched.split("?")[0]
    elif request.scope.get("path", "").startswith("/api/index.py"):
        sub = request.scope["path"][len("/api/index.py"):]
        request.scope["path"] = sub if sub else "/"
    elif request.scope.get("path", "").startswith("/index.py"):
        sub = request.scope["path"][len("/index.py"):]
        request.scope["path"] = sub if sub else "/"

    response = await call_next(request)
    return response


# Dual-register router prefixes to handle with or without /api
for prefix in [settings.api_prefix, "/v1"]:
    app.include_router(auth.router, prefix=prefix)
    app.include_router(rooms.router, prefix=prefix)
    app.include_router(bookings.router, prefix=prefix)


@app.get("/", tags=["meta"])
@app.get("/api", tags=["meta"])
@app.get("/api/index.py", include_in_schema=False)
@app.get("/index.py", include_in_schema=False)
def root_check() -> dict[str, str]:
    return {"status": "ok", "name": settings.app_name, "version": "0.1.0"}


@app.get("/health", tags=["health"])
@app.get("/api/health", tags=["health"])
def health_check() -> dict[str, str]:
    """Return process liveness without exposing configuration or secrets."""
    return {"status": "ok"}


@app.get("/api/docs", include_in_schema=False)
def docs_redirect():
    return RedirectResponse(url="/docs")


@app.get(f"{settings.api_prefix}/", tags=["meta"])
@app.get("/v1/", tags=["meta"])
def api_root() -> dict[str, str]:
    return {"name": settings.app_name, "version": "0.1.0"}
