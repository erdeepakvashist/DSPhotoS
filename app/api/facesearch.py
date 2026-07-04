"""Search the library with a face captured from the camera (or any uploaded image)."""
import base64

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import matching
from ..db import get_conn
from ..faces import get_engine

router = APIRouter(prefix="/api")

# Webcam captures are lower quality than photo-library faces, so be a bit more
# forgiving than the auto-tag threshold.
CAMERA_MATCH_THRESHOLD = 0.32
MAX_RESULTS = 300


class FaceSearchIn(BaseModel):
    image: str  # data URL or plain base64 JPEG/PNG


def _search_by_embedding(conn, q: np.ndarray, threshold: float) -> dict:
    rows = conn.execute(
        "SELECT photo_id, embedding FROM faces WHERE ignored=0").fetchall()
    if not rows:
        return {"error": None, "person": None, "items": []}
    mat = np.frombuffer(b"".join(r["embedding"] for r in rows),
                        dtype=np.float32).reshape(len(rows), -1)
    sims = mat @ q

    best_per_photo: dict[int, float] = {}
    for r, s in zip(rows, sims):
        pid = r["photo_id"]
        if s >= threshold and s > best_per_photo.get(pid, 0):
            best_per_photo[pid] = float(s)
    ranked = sorted(best_per_photo, key=best_per_photo.get, reverse=True)[:MAX_RESULTS]

    # name the person if the probe matches someone already tagged
    person = None
    pid_match, _ = matching.best_match(q, matching.person_centroids(conn), threshold)
    if pid_match:
        row = conn.execute("SELECT name FROM persons WHERE id=?", (pid_match,)).fetchone()
        person = row["name"] if row else None

    items = []
    if ranked:
        qmarks = ",".join("?" * len(ranked))
        by_id = {r["id"]: dict(r) for r in conn.execute(
            f"SELECT id, taken_at, width, height, favorite FROM photos WHERE id IN ({qmarks})",
            ranked)}
        items = [by_id[i] for i in ranked if i in by_id]
    return {"error": None, "person": person, "items": items}


@router.post("/search/face")
def search_by_face(body: FaceSearchIn):
    raw = base64.b64decode(body.image.split(",", 1)[-1])
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "Could not decode the captured image")

    found = get_engine().analyze(img)
    if not found:
        return {"error": "no_face", "person": None, "items": []}
    # use the largest face in the capture
    probe = max(found, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    return _search_by_embedding(get_conn(), probe.embedding, CAMERA_MATCH_THRESHOLD)


@router.get("/faces/{face_id}/similar")
def search_by_existing_face(face_id: int):
    """Reverse lookup for a face already in the library — click a face in the
    lightbox to find every other photo it appears in."""
    conn = get_conn()
    row = conn.execute("SELECT embedding FROM faces WHERE id=?", (face_id,)).fetchone()
    if not row:
        raise HTTPException(404, "No such face")
    q = np.frombuffer(row["embedding"], dtype=np.float32)
    return _search_by_embedding(conn, q, CAMERA_MATCH_THRESHOLD)
