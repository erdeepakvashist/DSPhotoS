"""Grid thumbnails and face crops, cached under data/thumbs/."""
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from .db import THUMBS_DIR, FACES_DIR

THUMB_SIZE = 400
FACE_SIZE = 180
FACE_MARGIN = 0.35  # extra context around the bbox


def thumb_path(photo_id: int) -> Path:
    return THUMBS_DIR / f"{photo_id}.jpg"


def face_path(face_id: int) -> Path:
    return FACES_DIR / f"{face_id}.jpg"


def make_thumb(img: Image.Image, photo_id: int):
    t = ImageOps.exif_transpose(img).copy()
    t.thumbnail((THUMB_SIZE, THUMB_SIZE))
    t.convert("RGB").save(thumb_path(photo_id), "JPEG", quality=82)


def make_face_crop(img_rgb: np.ndarray, bbox: tuple[float, float, float, float], face_id: int):
    h, w = img_rgb.shape[:2]
    x, y, bw, bh = bbox
    mx, my = bw * FACE_MARGIN, bh * FACE_MARGIN
    x1 = int(max(0, x - mx)); y1 = int(max(0, y - my))
    x2 = int(min(w, x + bw + mx)); y2 = int(min(h, y + bh + my))
    crop = Image.fromarray(img_rgb[y1:y2, x1:x2])
    crop.thumbnail((FACE_SIZE, FACE_SIZE))
    crop.convert("RGB").save(face_path(face_id), "JPEG", quality=85)
