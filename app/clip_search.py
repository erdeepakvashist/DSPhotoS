"""OpenCLIP ViT-B/32 image/text embeddings for free-text photo search (CPU)."""
import sqlite3
import threading

import numpy as np
from PIL import Image

_lock = threading.Lock()
_model = None
_preprocess = None
_tokenizer = None


def _load():
    global _model, _preprocess, _tokenizer
    with _lock:
        if _model is None:
            import open_clip
            import torch
            torch.set_num_threads(max(1, (torch.get_num_threads() or 4)))
            _model, _, _preprocess = open_clip.create_model_and_transforms(
                "ViT-B-32", pretrained="openai")
            _model.eval()
            _tokenizer = open_clip.get_tokenizer("ViT-B-32")
    return _model, _preprocess, _tokenizer


def embed_image(img: Image.Image) -> np.ndarray:
    import torch
    model, preprocess, _ = _load()
    with torch.no_grad():
        t = preprocess(img.convert("RGB")).unsqueeze(0)
        v = model.encode_image(t).squeeze(0).numpy().astype(np.float32)
    return v / (np.linalg.norm(v) + 1e-9)


def embed_text(query: str) -> np.ndarray:
    import torch
    model, _, tokenizer = _load()
    with torch.no_grad():
        v = model.encode_text(tokenizer([query])).squeeze(0).numpy().astype(np.float32)
    return v / (np.linalg.norm(v) + 1e-9)


def search(conn: sqlite3.Connection, query: str, limit: int = 400) -> list[int]:
    """Photo ids ranked by CLIP similarity to the text query."""
    rows = conn.execute("SELECT photo_id, embedding FROM clip_embeddings").fetchall()
    if not rows:
        return []
    q = embed_text(query)
    ids = np.array([r["photo_id"] for r in rows])
    mat = np.frombuffer(b"".join(r["embedding"] for r in rows), dtype=np.float32)
    mat = mat.reshape(len(rows), -1)
    sims = mat @ q
    order = np.argsort(-sims)
    keep = order[sims[order] >= 0.2][:limit]
    if len(keep) == 0:  # nothing crosses the floor — return best few anyway
        keep = order[:24]
    return [int(i) for i in ids[keep]]
