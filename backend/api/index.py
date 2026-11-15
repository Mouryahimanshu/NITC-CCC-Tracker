"""Vercel Serverless Function entry point for FastAPI backend."""

import os
import sys
from pathlib import Path

# Add the backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.main import app as fastapi_app


class VercelPathMiddleware:
    """Restores the original request path from Vercel edge headers (x-matched-path).

    When Vercel rewrites routes to /api/index.py, the ASGI scope['path'] can become
    '/api/index.py' instead of the requested path like '/health' or '/api/v1/...'.
    This middleware ensures FastAPI matches the route the client actually requested.
    """

    def __init__(self, asgi_app):
        self.app = asgi_app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            headers = dict(scope.get("headers", []))
            matched = headers.get(b"x-matched-path")
            if matched:
                matched_path = matched.decode("utf-8", errors="ignore").split("?")[0]
                if matched_path and not matched_path.endswith("index.py"):
                    scope["path"] = matched_path

            # Clean up any leftover /api/index.py prefix
            curr_path = scope.get("path", "")
            if curr_path.startswith("/api/index.py"):
                sub = curr_path[len("/api/index.py"):]
                scope["path"] = sub if sub else "/"
            elif curr_path.startswith("/index.py"):
                sub = curr_path[len("/index.py"):]
                scope["path"] = sub if sub else "/"

        await self.app(scope, receive, send)


app = VercelPathMiddleware(fastapi_app)
