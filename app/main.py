"""DeepakPhotoSearch — local Google Photos-style app. Run: uvicorn app.main:app"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import albums, people, photos, settings, timeline
from .db import init_db

STATIC = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="DeepakPhotoSearch")
init_db()

for r in (settings.router, timeline.router, people.router, albums.router, photos.router):
    app.include_router(r)

app.mount("/static", StaticFiles(directory=STATIC), name="static")


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
