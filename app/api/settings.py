"""Scan folders management + scan trigger/status + index stats + app lifecycle."""
import os
import subprocess
import sys
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from .. import archive, export, scanner
from ..db import get_conn, set_setting

router = APIRouter(prefix="/api")
ROOT = Path(__file__).resolve().parent.parent.parent


def _exit_soon():
    """Give the HTTP response time to flush, then terminate the process."""
    threading.Timer(0.7, lambda: os._exit(0)).start()


@router.post("/app/stop")
def app_stop():
    _exit_soon()
    return {"ok": True, "message": "App stopping — reopen with run.bat"}


@router.post("/app/restart")
def app_restart(request: Request):
    port = request.url.port or 8000
    py = str(ROOT / ".venv" / "Scripts" / "python.exe")
    # A detached process has no console, so cmd's `timeout` fails there; delay
    # in Python instead, then replace the bootstrap with the real server.
    boot = (f"import time, os; time.sleep(2); "
            f"os.execv({py!r}, [{py!r}, '-m', 'uvicorn', 'app.main:app', "
            f"'--host', '127.0.0.1', '--port', '{port}'])")
    # Detached processes have no console: without real stdout/stderr handles
    # uvicorn's log writes crash it, so send them to a log file.
    from ..db import DATA_DIR
    log = open(DATA_DIR / "server.log", "ab")
    subprocess.Popen([py, "-c", boot], cwd=str(ROOT),
                     stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                     creationflags=subprocess.DETACHED_PROCESS
                     | subprocess.CREATE_NEW_PROCESS_GROUP)
    _exit_soon()
    return {"ok": True}


class FolderIn(BaseModel):
    path: str


@router.get("/folders")
def list_folders():
    conn = get_conn()
    return [dict(r) for r in conn.execute("SELECT id, path FROM folders ORDER BY path")]


@router.post("/folders")
def add_folder(body: FolderIn):
    raw = body.path.strip().strip('"')
    if not os.path.isabs(raw) or ".." in Path(raw).parts:
        raise HTTPException(400, "Path must be an absolute folder path")
    path = os.path.realpath(raw)
    if not os.path.isdir(path):
        raise HTTPException(400, f"Not a folder: {path}")
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO folders(path) VALUES (?)", (path,))
    conn.commit()
    return {"ok": True}


@router.delete("/folders/{folder_id}")
def remove_folder(folder_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM folders WHERE id=?", (folder_id,))
    conn.commit()
    return {"ok": True}


_picker_lock = threading.Lock()


@router.get("/pick-folder")
def pick_folder(title: str = "Choose a photo folder"):
    """Open the native Windows folder dialog on this machine (the server and the
    browser are the same PC) and return the chosen path."""
    if not _picker_lock.acquire(blocking=False):
        raise HTTPException(409, "A folder dialog is already open — check your taskbar")
    try:
        import tkinter
        from tkinter import filedialog
        root = tkinter.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", 1)
        path = filedialog.askdirectory(parent=root, title=title)
        root.destroy()
        return {"path": os.path.normpath(path) if path else None}
    finally:
        _picker_lock.release()


@router.get("/settings/archive-folder")
def get_archive_folder():
    return {"path": archive.get_archive_folder(get_conn())}


@router.post("/settings/archive-folder")
def set_archive_folder(body: FolderIn):
    raw = body.path.strip().strip('"')
    if not os.path.isabs(raw) or ".." in Path(raw).parts:
        raise HTTPException(400, "Path must be an absolute folder path")
    path = os.path.realpath(raw)
    os.makedirs(path, exist_ok=True)
    set_setting(get_conn(), archive.ARCHIVE_FOLDER_SETTING, path)
    return {"ok": True, "path": path}


@router.delete("/settings/archive-folder")
def reset_archive_folder():
    """Back to the default: an 'Archive' folder beside each original."""
    conn = get_conn()
    conn.execute("DELETE FROM app_settings WHERE key=?", (archive.ARCHIVE_FOLDER_SETTING,))
    conn.commit()
    return {"ok": True}


@router.post("/scan")
def start_scan():
    if not scanner.start_scan():
        raise HTTPException(409, "Scan already running")
    return {"ok": True}


@router.post("/scan/backfill-sharpness")
def backfill_sharpness():
    """Score already-indexed photos for quality without a full re-scan — for
    photos indexed before quality scoring existed."""
    if not scanner.start_backfill_sharpness():
        raise HTTPException(409, "A scan is already running")
    return {"ok": True}


@router.post("/scan/stop")
def stop_scan():
    if not scanner.stop_scan():
        raise HTTPException(409, "No scan running")
    return {"ok": True}


@router.get("/export/csv")
def export_csv():
    csv_text = export.export_csv(get_conn())
    return Response(content=csv_text, media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="dsphotos_metadata.csv"'})


@router.get("/scan/status")
def scan_status():
    conn = get_conn()
    stats = {
        "photos": conn.execute("SELECT COUNT(*) c FROM photos").fetchone()["c"],
        "faces": conn.execute("SELECT COUNT(*) c FROM faces WHERE ignored=0").fetchone()["c"],
        "persons": conn.execute("SELECT COUNT(*) c FROM persons").fetchone()["c"],
        "clusters": conn.execute(
            "SELECT COUNT(DISTINCT cluster_id) c FROM faces "
            "WHERE cluster_id IS NOT NULL AND person_id IS NULL AND ignored=0").fetchone()["c"],
        "unscored": conn.execute(
            "SELECT COUNT(*) c FROM photos WHERE sharpness IS NULL").fetchone()["c"],
    }
    return {**scanner.STATUS, "stats": stats}
