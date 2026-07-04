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

import cv2
import numpy as np
from PIL import Image, ImageOps, ExifTags

from . import archive, clip_search, matching, smart_albums, thumbnails
from .db import get_conn
from .faces import get_engine

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
WORKERS = max(2, min(6, (os.cpu_count() or 4) - 2))

# Progress shared with /api/scan/status. 'state': idle | scanning | stopping | error
# 'phase' says what the scan is doing even before per-photo progress exists.
STATUS = {"state": "idle", "phase": "", "total": 0, "done": 0, "current": "",
          "new_photos": 0, "new_videos": 0, "error": ""}
_scan_lock = threading.Lock()
_stop = threading.Event()


def start_scan() -> bool:
    """Kick off a background scan. Returns False if one is already running."""
    if STATUS["state"] in ("scanning", "stopping"):
        return False
    _stop.clear()
    STATUS.update(state="scanning", phase="starting…", total=0, done=0, current="",
                  new_photos=0, new_videos=0, error="")
    threading.Thread(target=_run_scan, daemon=True).start()
    return True


def start_backfill_sharpness() -> bool:
    """Score already-indexed photos for quality (sharpness) without re-running
    face detection or CLIP embedding — for photos scanned before that scoring
    existed. Returns False if a scan/backfill is already running."""
    if STATUS["state"] in ("scanning", "stopping"):
        return False
    _stop.clear()
    STATUS.update(state="scanning", phase="starting…", total=0, done=0, current="",
                  new_photos=0, error="")
    threading.Thread(target=_run_backfill_sharpness, daemon=True).start()
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


def _run_backfill_sharpness():
    with _scan_lock:
        try:
            _backfill_sharpness()
            STATUS["state"] = "idle"
        except Exception as e:
            traceback.print_exc()
            STATUS.update(state="error", error=str(e))


def _backfill_sharpness():
    conn = get_conn()
    rows = conn.execute("SELECT id, path FROM photos WHERE sharpness IS NULL").fetchall()
    STATUS["total"] = len(rows)
    STATUS["phase"] = "scoring photo quality…" if rows else ""

    def score(row):
        try:
            img = ImageOps.exif_transpose(Image.open(row["path"]))
            return row["id"], _sharpness(np.asarray(img.convert("RGB")))
        except Exception:
            return row["id"], None  # unreadable/missing file — leave unscored

    with ThreadPoolExecutor(max_workers=WORKERS, initializer=_lower_thread_priority) as pool:
        for pid, score_val in pool.map(score, rows):
            if _stop.is_set():
                break
            if score_val is not None:
                conn.execute("UPDATE photos SET sharpness=? WHERE id=?", (score_val, pid))
            STATUS["done"] += 1
            if STATUS["done"] % 20 == 0:
                conn.commit()
    conn.commit()


def _custom_archive_path(conn) -> str | None:
    p = archive.get_archive_folder(conn)
    return os.path.normcase(os.path.normpath(p)) if p else None


def _find_changed_files(conn, folders, custom_archive, exts, table: str):
    """Walk `folders` for files with one of `exts`, skipping the Archive
    folder(s), and split into (todo, gone) against what's already in `table`:
    todo = new-or-modified files to (re)index, gone = previously-indexed
    paths that vanished from a still-reachable folder (and are removed from
    the table here)."""
    known = {r["path"]: r["mtime"] for r in conn.execute(f"SELECT path, mtime FROM {table}")}
    todo, seen = [], set()
    for root in folders:
        for dirpath, dirnames, filenames in os.walk(root):
            # "Archive" (or the user's configured archive folder, wherever it
            # is) holds photos/videos moved out of the library via duplicate
            # cleanup — never re-index them.
            dirnames[:] = [d for d in dirnames if d.lower() != "archive"
                          and (custom_archive is None
                               or os.path.normcase(os.path.normpath(os.path.join(dirpath, d)))
                               != custom_archive)]
            for fn in filenames:
                if os.path.splitext(fn)[1].lower() not in exts:
                    continue
                p = os.path.join(dirpath, fn)
                seen.add(p)
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
        conn.execute(f"DELETE FROM {table} WHERE path=?", (p,))
    if gone:
        conn.commit()
    return todo, gone


def _scan():
    conn = get_conn()  # scanner thread's own connection
    folders = [r["path"] for r in conn.execute("SELECT path FROM folders")]
    custom_archive = _custom_archive_path(conn)

    STATUS["phase"] = "finding photos…"
    photo_todo, photo_gone = _find_changed_files(conn, folders, custom_archive, IMAGE_EXTS, "photos")
    STATUS["phase"] = "finding videos…"
    video_todo, video_gone = _find_changed_files(conn, folders, custom_archive, VIDEO_EXTS, "videos")

    STATUS["total"] = len(photo_todo) + len(video_todo)
    STATUS["current"] = ""
    if photo_todo:
        STATUS["phase"] = "loading AI models (first run downloads them, ~650 MB)…"
        get_engine()  # load models once before workers start
        clip_search.embed_text("warmup")
    persons = matching.person_centroids(conn) if photo_todo else {}
    clusters = matching.cluster_centroids(conn) if photo_todo else {}

    if photo_todo:
        STATUS["phase"] = "indexing photos"
        # Sliding window of in-flight futures keeps memory bounded while all
        # WORKERS stay busy; results are stored in submission order.
        with ThreadPoolExecutor(max_workers=WORKERS, initializer=_lower_thread_priority) as pool:
            window = deque()
            todo_iter = iter(photo_todo)
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

    if video_todo and not _stop.is_set():
        STATUS["phase"] = "indexing videos"
        with ThreadPoolExecutor(max_workers=WORKERS, initializer=_lower_thread_priority) as pool:
            for (path, mtime), meta in zip(video_todo, pool.map(_video_metadata,
                                                                 (p for p, _ in video_todo))):
                if _stop.is_set():
                    break
                STATUS["current"] = os.path.basename(path)
                if meta is not None:
                    try:
                        _store_video(conn, path, mtime, meta)
                        STATUS["new_videos"] += 1
                    except Exception:
                        traceback.print_exc()
                STATUS["done"] += 1

    matching._drop_empty_clusters(conn)
    conn.commit()
    if STATUS["new_photos"] or photo_gone:
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
    sharpness = _sharpness(rgb)
    return {"path": path, "mtime": mtime, "w": w, "h": h, "taken_at": taken_at,
            "lat": lat, "lon": lon, "camera": camera, "thumb": thumb,
            "faces": faces, "clip": clip_emb, "sharpness": sharpness}


def _sharpness(rgb: np.ndarray) -> float:
    """Laplacian-variance blur score on a downscaled grayscale copy (higher =
    sharper); cheap enough to run on every photo alongside face/CLIP inference."""
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape[:2]
    scale = 800 / max(h, w)
    if scale < 1:
        gray = cv2.resize(gray, (int(w * scale), int(h * scale)))
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _store_photo(conn, r: dict, persons, clusters):
    """Scan thread: DB writes + matching (sequential), plus cheap JPEG saves."""
    conn.execute("DELETE FROM photos WHERE path=?", (r["path"],))  # re-index changed file
    photo_id = conn.execute(
        "INSERT INTO photos(path, mtime, width, height, taken_at, gps_lat, gps_lon, camera, sharpness) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (r["path"], r["mtime"], r["w"], r["h"], r["taken_at"], r["lat"], r["lon"],
         r["camera"], r["sharpness"])).lastrowid
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


def _video_metadata(path: str) -> dict | None:
    """Worker thread: probe a video for dimensions/duration and grab a
    representative frame for the thumbnail. No face/CLIP processing — videos
    aren't face- or text-searched (yet), just browsed in their own tab."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        cap.release()
        return None
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or None
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or None
    fps = cap.get(cv2.CAP_PROP_FPS) or 0
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    duration = (frame_count / fps) if fps > 0 else None
    # a frame ~1s in is a more representative thumbnail than frame 0 (often
    # black, or a lens cap) when the video is long enough to have one
    if fps and frame_count > fps:
        cap.set(cv2.CAP_PROP_POS_FRAMES, fps)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        return None
    thumb = thumbnails.thumb_image(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
    return {"width": width, "height": height, "duration": duration, "thumb": thumb}


def _store_video(conn, path: str, mtime: float, meta: dict):
    conn.execute("DELETE FROM videos WHERE path=?", (path,))  # re-index changed file
    taken_at = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
    video_id = conn.execute(
        "INSERT INTO videos(path, mtime, width, height, duration, taken_at) VALUES (?,?,?,?,?,?)",
        (path, mtime, meta["width"], meta["height"], meta["duration"], taken_at)).lastrowid
    meta["thumb"].save(thumbnails.video_thumb_path(video_id), "JPEG", quality=82)
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
