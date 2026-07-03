"""Albums CRUD + membership; favorites live on the photo row."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db import get_conn

router = APIRouter(prefix="/api")


class AlbumIn(BaseModel):
    name: str


class PhotosIn(BaseModel):
    photo_ids: list[int]


@router.get("/albums")
def list_albums():
    conn = get_conn()
    return [dict(r) for r in conn.execute(
        "SELECT a.id, a.name, a.auto, COUNT(ap.photo_id) photo_count, "
        "COALESCE(a.cover_photo_id, MIN(ap.photo_id)) cover "
        "FROM albums a LEFT JOIN album_photos ap ON ap.album_id=a.id "
        "GROUP BY a.id ORDER BY a.auto IS NOT NULL, a.created_at DESC")]


@router.post("/albums")
def create_album(body: AlbumIn):
    conn = get_conn()
    aid = conn.execute("INSERT INTO albums(name) VALUES (?)", (body.name.strip(),)).lastrowid
    conn.commit()
    return {"id": aid}


@router.patch("/albums/{album_id}")
def rename_album(album_id: int, body: AlbumIn):
    conn = get_conn()
    conn.execute("UPDATE albums SET name=? WHERE id=?", (body.name.strip(), album_id))
    conn.commit()
    return {"ok": True}


@router.delete("/albums/{album_id}")
def delete_album(album_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM albums WHERE id=?", (album_id,))
    conn.commit()
    return {"ok": True}


@router.post("/albums/{album_id}/photos")
def add_photos(album_id: int, body: PhotosIn):
    conn = get_conn()
    if not conn.execute("SELECT 1 FROM albums WHERE id=?", (album_id,)).fetchone():
        raise HTTPException(404, "No such album")
    conn.executemany("INSERT OR IGNORE INTO album_photos(album_id, photo_id) VALUES (?,?)",
                     [(album_id, pid) for pid in body.photo_ids])
    conn.commit()
    return {"ok": True}


@router.delete("/albums/{album_id}/photos")
def remove_photos(album_id: int, body: PhotosIn):
    conn = get_conn()
    conn.executemany("DELETE FROM album_photos WHERE album_id=? AND photo_id=?",
                     [(album_id, pid) for pid in body.photo_ids])
    conn.commit()
    return {"ok": True}
