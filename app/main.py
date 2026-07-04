"""DeepakPhotoSearch — local Google Photos-style app. Run: uvicorn app.main:app"""
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .api import albums, facesearch, people, photos, settings, timeline, videos
from .db import init_db

STATIC = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="DS PhotoS")
init_db()

for r in (settings.router, timeline.router, people.router, albums.router, photos.router,
          facesearch.router, videos.router):
    app.include_router(r)

app.mount("/static", StaticFiles(directory=STATIC), name="static")

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


@app.middleware("http")
async def block_cross_origin_writes(request, call_next):
    """Reject state-changing requests whose Origin/Referer isn't this machine, so a
    malicious webpage open in the browser can't drive the app via CSRF (e.g. an
    auto-submitting form posting to /api/scan or /app/stop) while it runs in the
    background."""
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        for header in ("origin", "referer"):
            value = request.headers.get(header)
            if value and urlparse(value).hostname not in LOCAL_HOSTS:
                return PlainTextResponse("Forbidden: cross-origin request", status_code=403)
    return await call_next(request)


@app.middleware("http")
async def no_stale_ui(request, call_next):
    """Force browsers to revalidate UI files so updates apply on a normal reload
    (media thumbs stay cacheable)."""
    response = await call_next(request)
    p = request.url.path
    if p == "/" or p.startswith("/static"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
