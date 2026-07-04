"""Privacy-safe copies for sharing: pixelate faces before a photo leaves the
machine, without ever touching the original file.
"""
import io
import os
import sqlite3

import cv2
import numpy as np
from PIL import Image


def blurred_photo_bytes(conn: sqlite3.Connection, photo_id: int, mode: str = "untagged") -> bytes | None:
    """JPEG bytes of the photo with faces pixelated. mode='untagged' blurs only
    faces with no assigned person (protects bystanders, keeps named people
    visible); mode='all' blurs every detected face."""
    row = conn.execute("SELECT path FROM photos WHERE id=?", (photo_id,)).fetchone()
    if not row or not os.path.exists(row["path"]):
        return None
    img = Image.open(row["path"]).convert("RGB")
    from PIL import ImageOps
    img = ImageOps.exif_transpose(img)
    arr = np.asarray(img).copy()

    where = "ignored=0" if mode == "all" else "ignored=0 AND person_id IS NULL"
    faces = conn.execute(
        f"SELECT bbox_x, bbox_y, bbox_w, bbox_h FROM faces WHERE photo_id=? AND {where}",
        (photo_id,)).fetchall()

    h, w = arr.shape[:2]
    for f in faces:
        x1 = max(0, int(f["bbox_x"]))
        y1 = max(0, int(f["bbox_y"]))
        x2 = min(w, int(f["bbox_x"] + f["bbox_w"]))
        y2 = min(h, int(f["bbox_y"] + f["bbox_h"]))
        if x2 <= x1 or y2 <= y1:
            continue
        region = arr[y1:y2, x1:x2]
        # shrink then blow back up (nearest-neighbor) for a strong pixelate effect
        small = cv2.resize(region, (max(1, (x2 - x1) // 12), max(1, (y2 - y1) // 12)),
                           interpolation=cv2.INTER_LINEAR)
        arr[y1:y2, x1:x2] = cv2.resize(small, (x2 - x1, y2 - y1), interpolation=cv2.INTER_NEAREST)

    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, "JPEG", quality=90)
    return buf.getvalue()
