"""Face detection (SCRFD det_10g) + recognition (ArcFace w600k_r50) via onnxruntime.

Uses InsightFace's buffalo_l ONNX models directly (auto-downloaded from the
official release) — same accuracy as the insightface package, no compiled deps.
"""
import threading
import urllib.request
import zipfile
from dataclasses import dataclass

import cv2
import numpy as np
import onnxruntime as ort

from .db import MODELS_DIR

BUFFALO_URL = "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip"
DET_MODEL = "det_10g.onnx"
REC_MODEL = "w600k_r50.onnx"
DET_SIZE = 640
DET_THRESH = 0.5
NMS_THRESH = 0.4

# Canonical 5-point landmark destinations for 112x112 ArcFace alignment.
ARC_DST = np.array(
    [[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
     [41.5493, 92.3655], [70.7299, 92.2041]], dtype=np.float32)


@dataclass
class Face:
    bbox: np.ndarray      # x1, y1, x2, y2 in original image coords
    kps: np.ndarray       # 5 x 2 landmarks
    det_score: float
    embedding: np.ndarray  # 512 float32, L2-normalized


def _ensure_models():
    det = MODELS_DIR / "buffalo_l" / DET_MODEL
    rec = MODELS_DIR / "buffalo_l" / REC_MODEL
    if det.exists() and rec.exists():
        return det, rec
    (MODELS_DIR / "buffalo_l").mkdir(parents=True, exist_ok=True)
    print("Downloading face models (buffalo_l, ~275 MB, one time)...")
    data, _ = urllib.request.urlretrieve(BUFFALO_URL)
    with zipfile.ZipFile(data) as zf:
        for name in zf.namelist():
            base = name.rsplit("/", 1)[-1]
            if base in (DET_MODEL, REC_MODEL):
                with zf.open(name) as src, open(MODELS_DIR / "buffalo_l" / base, "wb") as dst:
                    dst.write(src.read())
    print("Face models ready.")
    return det, rec


class FaceEngine:
    def __init__(self):
        det_path, rec_path = _ensure_models()
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        # Scanner runs several inferences concurrently; keep each one narrow so
        # they don't fight over cores.
        opts.intra_op_num_threads = 2
        self.det = ort.InferenceSession(str(det_path), opts, providers=["CPUExecutionProvider"])
        self.rec = ort.InferenceSession(str(rec_path), opts, providers=["CPUExecutionProvider"])
        self.det_input = self.det.get_inputs()[0].name
        self.rec_input = self.rec.get_inputs()[0].name

    # ---- detection (SCRFD) ----
    def detect(self, img_bgr: np.ndarray) -> list[Face]:
        h, w = img_bgr.shape[:2]
        scale = DET_SIZE / max(h, w)
        nh, nw = int(round(h * scale)), int(round(w * scale))
        resized = cv2.resize(img_bgr, (nw, nh))
        canvas = np.zeros((DET_SIZE, DET_SIZE, 3), dtype=np.uint8)
        canvas[:nh, :nw] = resized
        blob = cv2.dnn.blobFromImage(canvas, 1.0 / 128, (DET_SIZE, DET_SIZE),
                                     (127.5, 127.5, 127.5), swapRB=True)
        outs = self.det.run(None, {self.det_input: blob})

        strides = (8, 16, 32)
        scores_all, bboxes_all, kps_all = [], [], []
        for i, stride in enumerate(strides):
            scores = outs[i]
            bbox_pred = outs[i + 3] * stride
            kps_pred = outs[i + 6] * stride
            if scores.ndim == 3:  # batched model variant
                scores, bbox_pred, kps_pred = scores[0], bbox_pred[0], kps_pred[0]
            scores = scores.reshape(-1)
            side = DET_SIZE // stride
            centers = np.stack(np.mgrid[:side, :side][::-1], axis=-1).astype(np.float32)
            centers = (centers * stride).reshape(-1, 2)
            centers = np.stack([centers, centers], axis=1).reshape(-1, 2)  # 2 anchors/pos
            keep = scores >= DET_THRESH
            if not keep.any():
                continue
            c, d = centers[keep], bbox_pred.reshape(-1, 4)[keep]
            boxes = np.stack([c[:, 0] - d[:, 0], c[:, 1] - d[:, 1],
                              c[:, 0] + d[:, 2], c[:, 1] + d[:, 3]], axis=-1)
            k = kps_pred.reshape(-1, 10)[keep]
            kps = np.stack([c[:, 0:1] + k[:, 0::2], c[:, 1:2] + k[:, 1::2]], axis=-1)
            scores_all.append(scores[keep])
            bboxes_all.append(boxes)
            kps_all.append(kps)

        if not scores_all:
            return []
        scores = np.concatenate(scores_all)
        boxes = np.concatenate(bboxes_all) / scale
        kps = np.concatenate(kps_all) / scale
        keep = _nms(boxes, scores, NMS_THRESH)
        faces = []
        for i in keep:
            b = boxes[i]
            b[[0, 2]] = b[[0, 2]].clip(0, w)
            b[[1, 3]] = b[[1, 3]].clip(0, h)
            faces.append(Face(bbox=b, kps=kps[i], det_score=float(scores[i]), embedding=None))
        return faces

    # ---- recognition (ArcFace) ----
    def embed(self, img_bgr: np.ndarray, face: Face) -> np.ndarray:
        m, _ = cv2.estimateAffinePartial2D(face.kps.astype(np.float32), ARC_DST,
                                           method=cv2.LMEDS)
        aligned = cv2.warpAffine(img_bgr, m, (112, 112))
        blob = cv2.dnn.blobFromImage(aligned, 1.0 / 127.5, (112, 112),
                                     (127.5, 127.5, 127.5), swapRB=True)
        emb = self.rec.run(None, {self.rec_input: blob})[0].reshape(-1).astype(np.float32)
        emb /= np.linalg.norm(emb) + 1e-9
        face.embedding = emb
        return emb

    def analyze(self, img_bgr: np.ndarray) -> list[Face]:
        faces = self.detect(img_bgr)
        for f in faces:
            self.embed(img_bgr, f)
        return faces


def _nms(boxes: np.ndarray, scores: np.ndarray, thresh: float) -> list[int]:
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(int(i))
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-9)
        order = order[1:][iou <= thresh]
    return keep


_engine: FaceEngine | None = None
_engine_lock = threading.Lock()


def get_engine() -> FaceEngine:
    """Thread-safe lazy singleton; ort session.run() is safe to call concurrently."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = FaceEngine()
    return _engine
