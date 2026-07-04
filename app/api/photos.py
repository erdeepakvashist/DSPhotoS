"""Photo detail, favorite toggle, map markers, and media serving."""
import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import archive, dedup, hotspots
from ..db import get_conn
from ..thumbnails import face_path, thumb_path

router = APIRouter()


class PhotoIdsIn(BaseModel):
    photo_ids: list[int]


@router.get("/api/duplicates")
def duplicates():
    """Groups of near-identical photos (by CLIP similarity), best-resolution first."""
    conn = get_conn()
    groups = dedup.find_duplicate_groups(conn)
    out = []
    for group in groups:
        qmarks = ",".join("?" * len(group))
        rows = {r["id"]: dict(r) for r in conn.execute(
            f"SELECT id, taken_at, width, height, favorite FROM photos WHERE id IN ({qmarks})", group)}
        photos = [rows[i] for i in group if i in rows]
        photos.sort(key=lambda p: (p["width"] or 0) * (p["height"] or 0), reverse=True)
        if len(photos) > 1:
            out.append(photos)
    out.sort(key=len, reverse=True)
    return out


@router.post("/api/duplicates/archive")
def archive_duplicates(body: PhotoIdsIn):
    """Move the given photos' files into an 'Archive' folder beside their
    originals for the user to review/delete themselves; never deletes files."""
    conn = get_conn()
    archived, failed = [], []
    for pid in body.photo_ids:
        dest = archive.archive_photo(conn, pid)
        (archived if dest else failed).append(pid)
    return {"archived": archived, "failed": failed}


@router.get("/api/photos/{photo_id}")
def photo_detail(photo_id: int):
    conn = get_conn()
    p = conn.execute("SELECT * FROM photos WHERE id=?", (photo_id,)).fetchone()
    if not p:
        raise HTTPException(404, "No such photo")
    faces = [dict(r) for r in conn.execute(
        "SELECT f.id, f.bbox_x, f.bbox_y, f.bbox_w, f.bbox_h, f.person_id, f.assigned_by, "
        "pe.name person_name "
        "FROM faces f LEFT JOIN persons pe ON pe.id=f.person_id "
        "WHERE f.photo_id=? AND f.ignored=0 ORDER BY f.bbox_x", (photo_id,))]
    albums = [dict(r) for r in conn.execute(
        "SELECT a.id, a.name FROM albums a JOIN album_photos ap ON ap.album_id=a.id "
        "WHERE ap.photo_id=?", (photo_id,))]
    return {**{k: p[k] for k in p.keys() if k != "scanned_at"},
            "filename": os.path.basename(p["path"]), "faces": faces, "albums": albums}


@router.post("/api/photos/{photo_id}/favorite")
def toggle_favorite(photo_id: int):
    conn = get_conn()
    conn.execute("UPDATE photos SET favorite = 1 - favorite WHERE id=?", (photo_id,))
    conn.commit()
    row = conn.execute("SELECT favorite FROM photos WHERE id=?", (photo_id,)).fetchone()
    return {"favorite": row["favorite"] if row else 0}


@router.get("/api/map/markers")
def map_markers():
    conn = get_conn()
    return [dict(r) for r in conn.execute(
        "SELECT id, gps_lat lat, gps_lon lon, taken_at FROM photos "
        "WHERE gps_lat IS NOT NULL AND gps_lon IS NOT NULL")]


@router.get("/api/map/hotspots")
def map_hotspots():
    """Named places ranked by photo count, for the 'Top places' panel on the map."""
    return hotspots.top_places(get_conn())


@router.get("/media/photo/{photo_id}")
def media_photo(photo_id: int):
    conn = get_conn()
    row = conn.execute("SELECT path FROM photos WHERE id=?", (photo_id,)).fetchone()
    if not row or not os.path.exists(row["path"]):
        raise HTTPException(404, "Photo file missing")
    return FileResponse(row["path"])


@router.get("/media/thumb/{photo_id}")
def media_thumb(photo_id: int):
    p = thumb_path(photo_id)
    if not p.exists():
        return media_photo(photo_id)  # thumb missing -> serve original
    return FileResponse(p)


@router.get("/media/face/{face_id}")
def media_face(face_id: int):
    p = face_path(face_id)
    if not p.exists():
        raise HTTPException(404, "Face crop missing")
    return FileResponse(p)
