"""Folder walk + background indexing: EXIF, faces, matching, CLIP, thumbnails."""
import datetime
import os
import threading
import traceback

import numpy as np
from PIL import Image, ImageOps, ExifTags

from . import clip_search, matching, thumbnails
from .db import get_conn
from .faces import get_engine

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

# Progress shared with /api/scan/status. 'state': idle | scanning | error
STATUS = {"state": "idle", "total": 0, "done": 0, "current": "", "new_photos": 0, "error": ""}
_scan_lock = threading.Lock()


def start_scan() -> bool:
    """Kick off a background scan. Returns False if one is already running."""
    if STATUS["state"] == "scanning":
        return False
    STATUS.update(state="scanning", total=0, done=0, current="", new_photos=0, error="")
    threading.Thread(target=_run_scan, daemon=True).start()
    return True


def _run_scan():
    with _scan_lock:
        try:
            _scan()
            STATUS["state"] = "idle"
        except Exception as e:
            traceback.print_exc()
            STATUS.update(state="error", error=str(e))


def _scan():
    conn = get_conn()  # scanner thread's own connection
    folders = [r["path"] for r in conn.execute("SELECT path FROM folders")]

    # Collect candidate files, skipping already-indexed unchanged ones.
    known = {r["path"]: r["mtime"] for r in conn.execute("SELECT path, mtime FROM photos")}
    todo, seen = [], set()
    for root in folders:
        for dirpath, _, filenames in os.walk(root):
            for fn in filenames:
                if os.path.splitext(fn)[1].lower() not in IMAGE_EXTS:
                    continue
                p = os.path.join(dirpath, fn)
                seen.add(p)
                try:
                    mtime = os.path.getmtime(p)
                except OSError:
                    continue
                if known.get(p) != mtime:
                    todo.append((p, mtime))

    # Remove DB entries for files that no longer exist.
    gone = [p for p in known if p not in seen]
    for p in gone:
        conn.execute("DELETE FROM photos WHERE path=?", (p,))
    if gone:
        conn.commit()

    STATUS["total"] = len(todo)
    engine = get_engine() if todo else None
    persons = matching.person_centroids(conn) if todo else {}
    clusters = matching.cluster_centroids(conn) if todo else {}

    for path, mtime in todo:
        STATUS["current"] = os.path.basename(path)
        try:
            _index_photo(conn, engine, persons, clusters, path, mtime)
            STATUS["new_photos"] += 1
        except Exception:
            traceback.print_exc()  # skip unreadable/corrupt file, keep scanning
        STATUS["done"] += 1

    matching._drop_empty_clusters(conn)
    conn.commit()
    STATUS["current"] = ""


def _index_photo(conn, engine, persons, clusters, path: str, mtime: float):
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)  # bake orientation so bboxes match display
    taken_at, lat, lon, camera = _exif(img, path, mtime)
    rgb = np.asarray(img.convert("RGB"))
    h, w = rgb.shape[:2]

    conn.execute("DELETE FROM photos WHERE path=?", (path,))  # re-index changed file
    photo_id = conn.execute(
        "INSERT INTO photos(path, mtime, width, height, taken_at, gps_lat, gps_lon, camera) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (path, mtime, w, h, taken_at, lat, lon, camera)).lastrowid

    thumbnails.make_thumb(img, photo_id)

    bgr = rgb[:, :, ::-1].copy()
    for f in engine.analyze(bgr):
        x1, y1, x2, y2 = f.bbox
        face_id = conn.execute(
            "INSERT INTO faces(photo_id, bbox_x, bbox_y, bbox_w, bbox_h, det_score, embedding) "
            "VALUES (?,?,?,?,?,?,?)",
            (photo_id, float(x1), float(y1), float(x2 - x1), float(y2 - y1),
             f.det_score, f.embedding.tobytes())).lastrowid
        thumbnails.make_face_crop(rgb, (x1, y1, x2 - x1, y2 - y1), face_id)
        matching.assign_face(conn, face_id, f.embedding, persons, clusters)

    clip_emb = clip_search.embed_image(img)
    conn.execute("INSERT OR REPLACE INTO clip_embeddings(photo_id, embedding) VALUES (?,?)",
                 (photo_id, clip_emb.tobytes()))
    conn.commit()


def _exif(img: Image.Image, path: str, mtime: float):
    taken_at = lat = lon = camera = None
    try:
        exif = img.getexif()
        camera = exif.get(0x0110)  # Model
        ifd = exif.get_ifd(ExifTags.IFD.Exif)
        dto = ifd.get(0x9003) or exif.get(0x0132)  # DateTimeOriginal | DateTime
        if dto:
            taken_at = datetime.datetime.strptime(str(dto).strip(), "%Y:%m:%d %H:%M:%S") \
                .strftime("%Y-%m-%d %H:%M:%S")
        gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
        if gps and 2 in gps and 4 in gps:
            lat = _dms(gps[2]) * (-1 if gps.get(1) == "S" else 1)
            lon = _dms(gps[4]) * (-1 if gps.get(3) == "W" else 1)
    except Exception:
        pass
    if taken_at is None:
        taken_at = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
    return taken_at, lat, lon, (str(camera).strip() if camera else None)


def _dms(v) -> float:
    d, m, s = (float(x) for x in v)
    return d + m / 60 + s / 3600
