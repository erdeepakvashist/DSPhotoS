"""Scan folders management + scan trigger/status + index stats."""
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import scanner
from ..db import get_conn

router = APIRouter(prefix="/api")


class FolderIn(BaseModel):
    path: str


@router.get("/folders")
def list_folders():
    conn = get_conn()
    return [dict(r) for r in conn.execute("SELECT id, path FROM folders ORDER BY path")]


@router.post("/folders")
def add_folder(body: FolderIn):
    path = os.path.normpath(body.path.strip().strip('"'))
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


@router.post("/scan")
def start_scan():
    if not scanner.start_scan():
        raise HTTPException(409, "Scan already running")
    return {"ok": True}


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
    }
    return {**scanner.STATUS, "stats": stats}
