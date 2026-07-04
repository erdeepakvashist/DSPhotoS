"""Grid thumbnails and face crops, cached under data/thumbs/."""
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from .db import THUMBS_DIR, FACES_DIR, VIDEO_THUMBS_DIR

THUMB_SIZE = 400
FACE_SIZE = 180
FACE_MARGIN = 0.35  # extra context around the bbox


def thumb_path(photo_id: int) -> Path:
    return THUMBS_DIR / f"{int(photo_id)}.jpg"


def face_path(face_id: int) -> Path:
    return FACES_DIR / f"{int(face_id)}.jpg"


def video_thumb_path(video_id: int) -> Path:
    return VIDEO_THUMBS_DIR / f"{int(video_id)}.jpg"


def thumb_image(img: Image.Image) -> Image.Image:
    """Grid thumbnail as a PIL image (saved later once the photo id is known)."""
    t = ImageOps.exif_transpose(img).copy()
    t.thumbnail((THUMB_SIZE, THUMB_SIZE))
    return t.convert("RGB")


def face_crop_image(img_rgb: np.ndarray, bbox: tuple[float, float, float, float]) -> Image.Image:
    h, w = img_rgb.shape[:2]
    x, y, bw, bh = bbox
    mx, my = bw * FACE_MARGIN, bh * FACE_MARGIN
    x1 = int(max(0, x - mx)); y1 = int(max(0, y - my))
    x2 = int(min(w, x + bw + mx)); y2 = int(min(h, y + bh + my))
    crop = Image.fromarray(img_rgb[y1:y2, x1:x2])
    crop.thumbnail((FACE_SIZE, FACE_SIZE))
    return crop.convert("RGB")
