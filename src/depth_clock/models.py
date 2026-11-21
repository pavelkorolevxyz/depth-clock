"""The two ONNX models: relative depth and the main subject of a picture.

Both are downloaded once into the cache and checked by SHA-256.
  Depth Anything V2 Small  Apache-2.0  https://github.com/DepthAnything/Depth-Anything-V2
  ISNet general use        Apache-2.0  https://github.com/xuebinqin/DIS (ONNX export from rembg)
"""

import hashlib
import os
import sys
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

from depth_clock import paths

MODELS = {
    "depth": (
        "depth-anything-v2-small.onnx",
        "https://huggingface.co/onnx-community/depth-anything-v2-small/resolve/main/onnx/model.onnx",
        "afb6a5c28f3b6bf1618c6e43f02073ef9dfdc70e937502d51603e57b0a1df10c",
    ),
    "subject": (
        "isnet-general-use.onnx",
        "https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx",
        "60920e99c45464f2ba57bee2ad08c919a52bbf852739e96947fbb4358c0d964a",
    ),
}

_sessions = {}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def model_path(name: str) -> Path:
    file, url, sha = MODELS[name]
    path = paths.models() / file
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"depth-clock: downloading {file}", file=sys.stderr)
    tmp = path.with_suffix(".part")
    urllib.request.urlretrieve(url, tmp)
    if _sha256(tmp) != sha:
        tmp.unlink()
        raise RuntimeError(f"checksum mismatch for {file}")
    os.replace(tmp, path)
    return path


def _session(name: str):
    if name not in _sessions:
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        _sessions[name] = ort.InferenceSession(str(model_path(name)), opts, providers=["CPUExecutionProvider"])
    return _sessions[name]


def depth(img: Image.Image, height: int = 1036) -> np.ndarray:
    """Relative depth at the image's size, 0 far and 1 near."""
    s = _session("depth")
    W, H = img.size
    w = int(round(height * W / H / 14) * 14)
    x = np.asarray(img.resize((w, height), Image.BICUBIC), np.float32) / 255
    x = (x - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]
    d = s.run(None, {s.get_inputs()[0].name: x.transpose(2, 0, 1)[None].astype(np.float32)})[0].squeeze()
    d = (d - d.min()) / (d.max() - d.min() + 1e-6)
    return np.asarray(Image.fromarray(d.astype(np.float32), "F").resize((W, H), Image.BICUBIC), np.float32)


def subject(img: Image.Image) -> np.ndarray:
    """Where the main subject is, 0..1, at the image's size."""
    s = _session("subject")
    x = np.asarray(img.resize((1024, 1024), Image.LANCZOS), np.float32)
    x = x / max(x.max(), 1)
    x = (x - [0.485, 0.456, 0.406]) / [1.0, 1.0, 1.0]
    y = s.run(None, {s.get_inputs()[0].name: x.transpose(2, 0, 1)[None].astype(np.float32)})[0][:, 0]
    y = (y - y.min()) / (y.max() - y.min() + 1e-6)
    return np.asarray(Image.fromarray(y[0].astype(np.float32), "F").resize(img.size, Image.LANCZOS), np.float32).clip(0, 1)
