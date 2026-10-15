"""Local object detection (YOLOX) and face analysis (YuNet + SFace)."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from justai_sdk.plugin import HealthState, Plugin, PluginHealth
from justai_sdk.ports.vision import BBox, Detection, FaceObservation

COCO = ["person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
        "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog",
        "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
        "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite",
        "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket", "bottle",
        "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
        "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch", "potted plant",
        "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard", "cell phone",
        "microwave", "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase", "scissors",
        "teddy bear", "hair drier", "toothbrush"]

YOLOX_FILE = "object_detection_yolox_2022nov.onnx"
YUNET_FILE = "face_detection_yunet_2023mar.onnx"
SFACE_FILE = "face_recognition_sface_2021dec.onnx"


class YoloxDetector:
    detector_id = "yolox"
    labels = COCO
    INPUT = 640
    STRIDES = (8, 16, 32)

    def __init__(self, model: Path, threads: int = 2) -> None:
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        opts.inter_op_num_threads = 1
        opts.log_severity_level = 3
        providers = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider")
                     if p in ort.get_available_providers()]
        self.session = ort.InferenceSession(str(model), sess_options=opts, providers=providers)
        self.input_name = self.session.get_inputs()[0].name
        grids, strides = [], []
        for stride in self.STRIDES:
            size = self.INPUT // stride
            xv, yv = np.meshgrid(np.arange(size), np.arange(size))
            grids.append(np.stack((xv, yv), 2).reshape(-1, 2))
            strides.append(np.full((size * size, 1), stride))
        self.grids = np.concatenate(grids).astype(np.float32)
        self.strides = np.concatenate(strides).astype(np.float32)

    def detect(self, image: np.ndarray, min_score: float = 0.4) -> list[Detection]:
        h, w = image.shape[:2]
        ratio = min(self.INPUT / h, self.INPUT / w)
        rh, rw = int(h * ratio), int(w * ratio)
        padded = np.full((self.INPUT, self.INPUT, 3), 114, dtype=np.float32)
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        padded[:rh, :rw] = cv2.resize(rgb, (rw, rh), interpolation=cv2.INTER_LINEAR)
        blob = np.transpose(padded, (2, 0, 1))[None]
        out = self.session.run(None, {self.input_name: blob})[0][0]
        out[:, :2] = (out[:, :2] + self.grids) * self.strides
        out[:, 2:4] = np.exp(out[:, 2:4]) * self.strides
        scores = out[:, 4:5] * out[:, 5:]
        cls = np.argmax(scores, axis=1)
        conf = scores[np.arange(scores.shape[0]), cls]
        keep = conf >= min_score
        if not keep.any():
            return []
        boxes, conf, cls = out[keep, :4], conf[keep], cls[keep]
        xywh = np.stack([boxes[:, 0] - boxes[:, 2] / 2, boxes[:, 1] - boxes[:, 3] / 2,
                         boxes[:, 2], boxes[:, 3]], axis=1) / ratio
        idx = cv2.dnn.NMSBoxesBatched(xywh.tolist(), conf.tolist(), cls.tolist(), min_score, 0.45)
        result = []
        for i in np.array(idx).reshape(-1):
            x, y, bw, bh = xywh[i]
            x0, y0 = max(0.0, x), max(0.0, y)
            x1, y1 = min(float(w), x + bw), min(float(h), y + bh)
            result.append(Detection(label=COCO[int(cls[i])], score=float(conf[i]),
                                    bbox=BBox(x=x0 / w, y=y0 / h, w=(x1 - x0) / w, h=(y1 - y0) / h)))
        return result


class OpenCVFaceAnalyzer:
    analyzer_id = "opencv-sface"
    embedding_model = "sface-2021dec"
    embedding_dim = 128

    def __init__(self, models_dir: Path, match: float, strong: float) -> None:
        self.match_threshold = match
        self.strong_match_threshold = strong
        self._yunet = str(models_dir / YUNET_FILE)
        self._sface = str(models_dir / SFACE_FILE)
        self._local = threading.local()  # OpenCV DNN objects are not thread-safe

    def _models(self) -> tuple[Any, Any]:
        loc = self._local
        if not hasattr(loc, "det"):
            loc.det = cv2.FaceDetectorYN.create(self._yunet, "", (320, 320), 0.75, 0.3, 50)
            loc.rec = cv2.FaceRecognizerSF.create(self._sface, "")
        return loc.det, loc.rec

    def detect_faces(self, image: np.ndarray) -> list[FaceObservation]:
        det, _ = self._models()
        h, w = image.shape[:2]
        det.setInputSize((w, h))
        _, faces = det.detect(image)
        out: list[FaceObservation] = []
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        for f in faces if faces is not None else []:
            x, y, fw, fh = (float(v) for v in f[:4])
            landmarks = [(float(f[4 + 2 * i]) / w, float(f[5 + 2 * i]) / h) for i in range(5)]
            x0, y0 = int(max(0, x)), int(max(0, y))
            crop = gray[y0 : int(min(h, y + fh)), x0 : int(min(w, x + fw))]
            sharp = float(cv2.Laplacian(crop, cv2.CV_64F).var()) if crop.size else 0.0
            bright = float(crop.mean()) if crop.size else 0.0
            # Frontalness: nose between the eyes and mouth corners symmetric.
            (rex, _), (lex, _), (nx, _), _, _ = landmarks
            eye_mid = (rex + lex) / 2
            eye_dist = abs(lex - rex) + 1e-6
            frontal = max(0.0, 1.0 - abs(nx - eye_mid) / eye_dist * 2)
            out.append(FaceObservation(
                bbox=BBox(x=x / w, y=y / h, w=fw / w, h=fh / h), score=float(f[14]),
                landmarks=landmarks, raw=[float(v) for v in f[:15]], sharpness=sharp,
                brightness=bright, size_px=int(min(fw, fh)), frontalness=frontal))
        return out

    def embed(self, image: np.ndarray, face: FaceObservation) -> np.ndarray:
        _, rec = self._models()
        aligned = rec.alignCrop(image, np.array(face.raw, dtype=np.float32))
        feature = rec.feature(aligned).reshape(-1).astype(np.float32)
        return feature / (np.linalg.norm(feature) + 1e-9)


class VisionOpenCVPlugin(Plugin):
    async def setup(self) -> None:
        root = os.environ.get("JUSTAI_MODELS_DIR", "/models")
        self.models_dir = Path(self.ctx.config.get("models_dir") or f"{root}/vision")
        threads = int(self.ctx.config.get("threads", 2))
        if (self.models_dir / YOLOX_FILE).exists():
            self.ctx.register_provider("object_detector", YoloxDetector(self.models_dir / YOLOX_FILE, threads))
        if (self.models_dir / YUNET_FILE).exists() and (self.models_dir / SFACE_FILE).exists():
            self.ctx.register_provider("face_analyzer", OpenCVFaceAnalyzer(
                self.models_dir, float(self.ctx.config.get("face_match_threshold", 0.40)),
                float(self.ctx.config.get("face_strong_threshold", 0.52))))

    async def health(self) -> PluginHealth:
        missing = [f for f in (YOLOX_FILE, YUNET_FILE, SFACE_FILE) if not (self.models_dir / f).exists()]
        if missing:
            return PluginHealth(state=HealthState.DEGRADED, detail=f"missing models: {missing}")
        return PluginHealth()
