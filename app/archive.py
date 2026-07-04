"""Move photos out of the library into a sibling 'Archive' folder for the user
to review and permanently delete themselves — the app never deletes files.

Archived files sit in an 'Archive' subfolder next to the originals, which the
scanner (scanner.py) skips, so they never come back as new photos.
"""
import os
import shutil
import sqlite3

from .db import get_conn
from .thumbnails import face_path, thumb_path


def _unique_dest(archive_dir: str, filename: str) -> str:
    dest = os.path.join(archive_dir, filename)
    if not os.path.exists(dest):
        return dest
    stem, ext = os.path.splitext(filename)
    n = 1
    while os.path.exists(dest := os.path.join(archive_dir, f"{stem} ({n}){ext}")):
        n += 1
    return dest


def archive_photo(conn: sqlite3.Connection, photo_id: int) -> str | None:
    """Move one photo's file into an 'Archive' folder beside it, then drop its
    DB row (faces/tags/album membership cascade away with it). Returns the new
    path, or None if the photo/file no longer exists."""
    row = conn.execute("SELECT path FROM photos WHERE id=?", (photo_id,)).fetchone()
    if not row or not os.path.exists(row["path"]):
        return None
    src = row["path"]
    archive_dir = os.path.join(os.path.dirname(src), "Archive")
    os.makedirs(archive_dir, exist_ok=True)
    dest = _unique_dest(archive_dir, os.path.basename(src))
    shutil.move(src, dest)

    conn.execute("DELETE FROM photos WHERE id=?", (photo_id,))
    conn.commit()
    for p in (thumb_path(photo_id),):
        p.unlink(missing_ok=True)
    return dest
