"""Video listing, detail, and media serving (thumbnail + range-request
playback). Videos get a thumbnail + duration/dimensions on scan, but no face
detection or CLIP embedding — they're browsed in their own tab, not searched.
"""
import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..db import get_conn
from ..thumbnails import video_thumb_path

router = APIRouter()
PAGE = 60


@router.get("/api/videos")
def list_videos(cursor: str = ""):
    conn = get_conn()
    where, params = ["1=1"], []
    if cursor:
        taken, vid = cursor.rsplit("|", 1)
        where.append("(taken_at < ? OR (taken_at = ? AND id < ?))")
        params += [taken, taken, int(vid)]
    rows = conn.execute(
        f"SELECT id, taken_at, width, height, duration FROM videos "
        f"WHERE {' AND '.join(where)} ORDER BY taken_at DESC, id DESC LIMIT {PAGE + 1}",
        params).fetchall()
    items = [dict(r) for r in rows[:PAGE]]
    next_cursor = None
    if len(rows) > PAGE:
        last = items[-1]
        next_cursor = f"{last['taken_at']}|{last['id']}"
    return {"items": items, "next_cursor": next_cursor}


@router.get("/api/videos/{video_id}")
def video_detail(video_id: int):
    conn = get_conn()
    v = conn.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
    if not v:
        raise HTTPException(404, "No such video")
    return {**{k: v[k] for k in v.keys() if k != "scanned_at"},
            "filename": os.path.basename(v["path"])}


@router.get("/media/video/{video_id}")
def media_video(video_id: int):
    conn = get_conn()
    row = conn.execute("SELECT path FROM videos WHERE id=?", (video_id,)).fetchone()
    if not row or not os.path.exists(row["path"]):
        raise HTTPException(404, "Video file missing")
    return FileResponse(row["path"])  # Starlette handles Range requests for seeking


@router.get("/media/video-thumb/{video_id}")
def media_video_thumb(video_id: int):
    p = video_thumb_path(video_id)
    if not p.exists():
        raise HTTPException(404, "Thumbnail missing")
    return FileResponse(p)
