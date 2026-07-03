"""Folder walk + background indexing: EXIF, faces, matching, CLIP, thumbnails.

Heavy per-photo work (decode, face detection, CLIP, thumbnail encoding) runs in a
worker thread pool; the scan thread consumes results in order and does the parts
that must stay sequential: DB writes and person/cluster matching.
"""
import datetime
import os
import threading
import traceback
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image, ImageOps, ExifTags

from . import clip_search, matching, smart_albums, thumbnails
from .db import get_conn
from .faces import get_engine

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
WORKERS = max(2, min(6, (os.cpu_count() or 4) - 2))

# Progress shared with /api/scan/status. 'state': idle | scanning | stopping | error
# 'phase' says what the scan is doing even before per-photo progress exists.
STATUS = {"state": "idle", "phase": "", "total": 0, "done": 0, "current": "",
          "new_photos": 0, "error": ""}
_scan_lock = threading.Lock()
_stop = threading.Event()


def start_scan() -> bool:
    """Kick off a background scan. Returns False if one is already running."""
    if STATUS["state"] in ("scanning", "stopping"):
        return False
    _stop.clear()
    STATUS.update(state="scanning", phase="starting…", total=0, done=0, current="",
                  new_photos=0, error="")
    threading.Thread(target=_run_scan, daemon=True).start()
    return True


def _lower_thread_priority():
    """Workers run below normal priority so the web UI stays responsive while
    the CPU is saturated with inference."""
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.SetThreadPriority(k32.GetCurrentThread(), -1)  # THREAD_PRIORITY_BELOW_NORMAL
    except Exception:
        pass


def stop_scan() -> bool:
    """Ask a running scan to stop; already-indexed photos are kept, the rest are
    picked up by the next scan."""
    if STATUS["state"] != "scanning":
        return False
    STATUS["state"] = "stopping"
    _stop.set()
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
    STATUS["phase"] = "finding photos…"
    known = {r["path"]: r["mtime"] for r in conn.execute("SELECT path, mtime FROM photos")}
    todo, seen = [], set()
    for root in folders:
        for dirpath, _, filenames in os.walk(root):
            for fn in filenames:
                if os.path.splitext(fn)[1].lower() not in IMAGE_EXTS:
                    continue
                p = os.path.join(dirpath, fn)
                seen.add(p)
                if len(seen) % 500 == 0:
                    STATUS["current"] = f"{len(seen)} files found, {len(todo)} new"
                try:
                    mtime = os.path.getmtime(p)
                except OSError:
                    continue
                if known.get(p) != mtime:
                    todo.append((p, mtime))

    # Remove DB entries only for files that vanished from a still-configured,
    # currently-reachable folder. Files under removed/offline roots (unplugged
    # drive, OneDrive offline) are kept so tags are never wiped by accident.
    reachable = [os.path.normcase(r) for r in folders if os.path.isdir(r)]
    def _under_reachable(p: str) -> bool:
        n = os.path.normcase(p)
        return any(n.startswith(r.rstrip("\\/") + os.sep) for r in reachable)
    gone = [p for p in known if p not in seen and _under_reachable(p)]
    for p in gone:
        conn.execute("DELETE FROM photos WHERE path=?", (p,))
    if gone:
        conn.commit()

    STATUS["total"] = len(todo)
    STATUS["current"] = ""
    if todo:
        STATUS["phase"] = "loading AI models (first run downloads them, ~650 MB)…"
        get_engine()  # load models once before workers start
        clip_search.embed_text("warmup")
    persons = matching.person_centroids(conn) if todo else {}
    clusters = matching.cluster_centroids(conn) if todo else {}
    STATUS["phase"] = "indexing photos" if todo else ""

    # Sliding window of in-flight futures keeps memory bounded while all
    # WORKERS stay busy; results are stored in submission order.
    with ThreadPoolExecutor(max_workers=WORKERS, initializer=_lower_thread_priority) as pool:
        window = deque()
        todo_iter = iter(todo)
        while True:
            if _stop.is_set():
                for fut, _ in window:
                    fut.cancel()  # queued tasks; already-running ones just finish
                break
            while len(window) < WORKERS * 2:
                nxt = next(todo_iter, None)
                if nxt is None:
                    break
                window.append((pool.submit(_process_photo, *nxt), nxt))
            if not window:
                break
            fut, (path, mtime) = window.popleft()
            STATUS["current"] = os.path.basename(path)
            try:
                _store_photo(conn, fut.result(), persons, clusters)
                STATUS["new_photos"] += 1
            except Exception:
                traceback.print_exc()  # skip unreadable/corrupt file, keep scanning
            STATUS["done"] += 1

    matching._drop_empty_clusters(conn)
    conn.commit()
    if STATUS["new_photos"] or gone:
        STATUS.update(phase="building smart albums…", current="")
        try:
            smart_albums.regenerate(conn)
        except Exception:
            traceback.print_exc()  # smart albums are best-effort
    STATUS.update(phase="", current="")


def _process_photo(path: str, mtime: float) -> dict:
    """Worker thread: all heavy compute, no DB access."""
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)  # bake orientation so bboxes match display
    taken_at, lat, lon, camera = _exif(img, path, mtime)
    rgb = np.asarray(img.convert("RGB"))
    h, w = rgb.shape[:2]

    thumb = thumbnails.thumb_image(img)
    bgr = rgb[:, :, ::-1].copy()
    faces = []
    for f in get_engine().analyze(bgr):
        x1, y1, x2, y2 = f.bbox
        bbox = (float(x1), float(y1), float(x2 - x1), float(y2 - y1))
        faces.append({"bbox": bbox, "det_score": f.det_score, "embedding": f.embedding,
                      "crop": thumbnails.face_crop_image(rgb, bbox)})
    clip_emb = clip_search.embed_image(img)
    return {"path": path, "mtime": mtime, "w": w, "h": h, "taken_at": taken_at,
            "lat": lat, "lon": lon, "camera": camera, "thumb": thumb,
            "faces": faces, "clip": clip_emb}


def _store_photo(conn, r: dict, persons, clusters):
    """Scan thread: DB writes + matching (sequential), plus cheap JPEG saves."""
    conn.execute("DELETE FROM photos WHERE path=?", (r["path"],))  # re-index changed file
    photo_id = conn.execute(
        "INSERT INTO photos(path, mtime, width, height, taken_at, gps_lat, gps_lon, camera) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (r["path"], r["mtime"], r["w"], r["h"], r["taken_at"], r["lat"], r["lon"],
         r["camera"])).lastrowid
    r["thumb"].save(thumbnails.thumb_path(photo_id), "JPEG", quality=82)

    for f in r["faces"]:
        x, y, w, h = f["bbox"]
        face_id = conn.execute(
            "INSERT INTO faces(photo_id, bbox_x, bbox_y, bbox_w, bbox_h, det_score, embedding) "
            "VALUES (?,?,?,?,?,?,?)",
            (photo_id, x, y, w, h, f["det_score"], f["embedding"].tobytes())).lastrowid
        f["crop"].save(thumbnails.face_path(face_id), "JPEG", quality=85)
        matching.assign_face(conn, face_id, f["embedding"], persons, clusters)

    conn.execute("INSERT OR REPLACE INTO clip_embeddings(photo_id, embedding) VALUES (?,?)",
                 (photo_id, r["clip"].tobytes()))
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
