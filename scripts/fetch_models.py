#!/usr/bin/env python3
"""Download all models JuStAI5 needs for fully local operation.

Used at image build time (``docker/core.Dockerfile``) so the running system needs no
internet access for wakeword, VAD, STT, TTS, embeddings and vision. Files with a
known SHA-256 are verified.

Usage: python scripts/fetch_models.py /models
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

OWW = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/"
PIPER = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
ZOO = "https://huggingface.co/opencv/"

FILES: list[tuple[str, str, str]] = [
    # (target, url, sha256)
    ("openwakeword/melspectrogram.onnx", OWW + "melspectrogram.onnx",
     "ba2b0e0f8b7b875369a2c89cb13360ff53bac436f2895cced9f479fa65eb176f"),
    ("openwakeword/embedding_model.onnx", OWW + "embedding_model.onnx",
     "70d164290c1d095d1d4ee149bc5e00543250a7316b59f31d056cff7bd3075c1f"),
    ("openwakeword/hey_jarvis_v0.1.onnx", OWW + "hey_jarvis_v0.1.onnx",
     "94a13cfe60075b132f6a472e7e462e8123ee70861bc3fb58434a73712ee0d2cb"),
    ("openwakeword/alexa_v0.1.onnx", OWW + "alexa_v0.1.onnx",
     "6ff566a01d12670e8d9e3c59da32651db1575d17272a601b7f8a39283dfbae3e"),
    ("openwakeword/hey_mycroft_v0.1.onnx", OWW + "hey_mycroft_v0.1.onnx",
     "c2a311e8fa1338de89c31b3b46dc4dffd4af2f9a8d6ddead48893c2d301b1f18"),
    ("openwakeword/hey_rhasspy_v0.1.onnx", OWW + "hey_rhasspy_v0.1.onnx",
     "5a9b3ed3be2910e35780e097905aa9f35a9c10038df47914cf2b3ec4d670f6ea"),
    ("piper/de_DE-thorsten-medium.onnx", PIPER + "de/de_DE/thorsten/medium/de_DE-thorsten-medium.onnx",
     "7e64762d8e5118bb578f2eea6207e1a35a8e0c30595010b666f983fc87bb7819"),
    ("piper/de_DE-thorsten-medium.onnx.json", PIPER + "de/de_DE/thorsten/medium/de_DE-thorsten-medium.onnx.json",
     "974adee790533adb273a1ac88f49027d2a1b8f0f2cf4905954a4791e79264e85"),
    ("piper/it_IT-paola-medium.onnx", PIPER + "it/it_IT/paola/medium/it_IT-paola-medium.onnx",
     "6fc918b5a0ea6137382833dddfa567bffbe6a5060c02043c87192ee59c04210c"),
    ("piper/it_IT-paola-medium.onnx.json", PIPER + "it/it_IT/paola/medium/it_IT-paola-medium.onnx.json",
     "aea19c0a7fce29fbc359b93f10e7902854401e4c95ae2ea328ae516b15d296cf"),
    ("piper/en_US-lessac-medium.onnx", PIPER + "en/en_US/lessac/medium/en_US-lessac-medium.onnx",
     "5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f"),
    ("piper/en_US-lessac-medium.onnx.json", PIPER + "en/en_US/lessac/medium/en_US-lessac-medium.onnx.json",
     "efe19c417bed055f2d69908248c6ba650fa135bc868b0e6abb3da181dab690a0"),
    ("vision/object_detection_yolox_2022nov.onnx",
     ZOO + "object_detection_yolox/resolve/main/object_detection_yolox_2022nov.onnx",
     "c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063"),
    ("vision/face_detection_yunet_2023mar.onnx",
     ZOO + "face_detection_yunet/resolve/main/face_detection_yunet_2023mar.onnx",
     "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"),
    ("vision/face_recognition_sface_2021dec.onnx",
     ZOO + "face_recognition_sface/resolve/main/face_recognition_sface_2021dec.onnx",
     "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"),
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download(root: Path) -> None:
    for target, url, digest in FILES:
        path = root / target
        if path.exists() and sha256(path) == digest:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading {target}", flush=True)
        tmp = path.with_suffix(path.suffix + ".part")
        urllib.request.urlretrieve(url, tmp)  # noqa: S310 (fixed https URLs)
        actual = sha256(tmp)
        if actual != digest:
            tmp.unlink()
            raise SystemExit(f"checksum mismatch for {target}: {actual}")
        tmp.rename(path)

    # Models fetched through their libraries (Hugging Face Hub, pinned by name).
    from faster_whisper import download_model

    print("downloading whisper small", flush=True)
    download_model("small", cache_dir=str(root / "whisper"))

    from fastembed import TextEmbedding

    print("downloading multilingual embedding model", flush=True)
    TextEmbedding("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                  cache_dir=str(root / "fastembed"))


if __name__ == "__main__":
    download(Path(sys.argv[1] if len(sys.argv) > 1 else "/models"))
