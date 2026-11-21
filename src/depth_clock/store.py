"""The analysis cache, the user's placements, and current.json for the clock.

Cache, one directory per wallpaper (by content hash):
  analysis.json  layers and ranked placements
  layer-N.png    what stands in front, layer N (N >= 1)
  dark-N.png     digit color for dark digits behind layer N (N >= 0)
  light-N.png    the same for light digits
  depth.npy, subject.npy  model outputs, reused when the analysis changes

placements.json, in the config directory, keeps what the user picked for each
wallpaper. It wins over the analysis.
"""

import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path

from depth_clock import paths

VERSION = 1


def atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(data)
    os.replace(tmp, path)


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def wallpaper_key(path: Path) -> str:
    h = hashlib.blake2b(digest_size=8)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def entry_dir(key: str) -> Path:
    """Places depend on the font's shapes, so each font gets its own analysis."""
    import re

    from depth_clock.geometry import font_name

    font = re.sub(r"[^a-z0-9]+", "-", font_name().lower()).strip("-")
    return paths.cache() / f"{key}-v{VERSION}-{font}"


@contextlib.contextmanager
def locked():
    """One analysis at a time: the clock may ask again while one runs."""
    paths.cache().mkdir(parents=True, exist_ok=True)
    with open(paths.cache() / "lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def manual_mask(wallpaper: Path):
    for d in paths.mask_dirs():
        p = d / f"{wallpaper.stem}.png"
        if p.exists():
            return p
    return None


def analysis(wallpaper: Path, force: bool = False) -> dict:
    """Analyze once per wallpaper; later calls read the cache."""
    key = wallpaper_key(wallpaper)
    d = entry_dir(key)
    found = read_json(d / "analysis.json", None)
    if found and not force:
        return found
    with locked():
        found = read_json(d / "analysis.json", None)
        if found and not force:
            return found
        return _run(wallpaper, key, d)


def _run(wallpaper: Path, key: str, d: Path) -> dict:
    import numpy as np
    from PIL import Image

    from depth_clock import analyze as A
    from depth_clock import models

    d.mkdir(parents=True, exist_ok=True)
    img = A.load_frame(wallpaper)

    def cached(name, fn):
        f = d.parent / f"{key}.{name}.npy"
        if f.exists():
            return np.load(f)
        v = fn(img)
        np.save(f, v)
        return v

    manual = None
    mpath = manual_mask(wallpaper)
    if mpath:
        alpha = Image.open(mpath).convert("RGBA").getchannel("A")
        manual = np.asarray(_cover(alpha, img.size), np.float32) / 255
    depth = None if manual is not None else cached("depth", models.depth)
    subject = cached("subject", models.subject)

    res = A.analyze(img, depth, subject, manual)
    layers = []
    for i, layer in enumerate(res["layers"]):
        entry = {"index": i, "ridge": layer["ridge"], "peaks": layer["peaks"], "mask": ""}
        if layer["mask"] is not None:
            A.mask_image(layer["mask"], img).save(d / f"layer-{i}.png", optimize=True)
            entry["mask"] = f"layer-{i}.png"
        A.tint_image(layer["dark"]).save(d / f"dark-{i}.png")
        A.tint_image(layer["light"]).save(d / f"light-{i}.png")
        entry["dark"], entry["light"] = f"dark-{i}.png", f"light-{i}.png"
        layers.append(entry)
    out = {
        "version": VERSION, "wallpaper": str(wallpaper), "key": key,
        "manual": str(mpath) if mpath else None,
        "layers": layers, "candidates": res["candidates"],
    }
    atomic_write(d / "analysis.json", json.dumps(out, indent=1))
    return out


def _cover(img, size):
    """Scale to cover and center-crop, like the wallpaper itself."""
    from PIL import Image

    W, H = size
    s = max(W / img.width, H / img.height)
    img = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
    left, top = (img.width - W) // 2, (img.height - H) // 2
    return img.crop((left, top, left + W, top + H))


def placements() -> dict:
    return read_json(paths.placements(), {})


def save_placement(key: str, value: dict | None) -> None:
    data = placements()
    if value is None:
        data.pop(key, None)
    else:
        data[key] = value
    atomic_write(paths.placements(), json.dumps(data, indent=1, sort_keys=True))


def resolve(an: dict) -> dict:
    """The placement in effect: the user's, or the best one found."""
    user = placements().get(an["key"])
    if user:
        return {**user, "source": "user"}
    best = an["candidates"][0]
    return {"layer": best["layer"], "cx": best["cx"], "baseline": best["baseline"], "size": best["size"],
            "mode": "auto", "candidate": 0, "source": "auto"}


def resolved_mode(an: dict, p: dict) -> str:
    if p.get("mode") in ("dark", "light"):
        return p["mode"]
    i = p.get("candidate")
    if i is not None and i < len(an["candidates"]):
        c = an["candidates"][i]
        if (c["layer"], c["cx"], c["baseline"], c["size"]) == (p["layer"], p["cx"], p["baseline"], p["size"]):
            return c["mode"]
    return mode_for(an, p)


def mode_for(an: dict, p: dict) -> str:
    """Dark or light for any placement, from the stored tints and mask."""
    import numpy as np
    from PIL import Image

    from depth_clock import analyze as A
    from depth_clock.geometry import Placement

    d = entry_dir(an["key"])
    layer = an["layers"][p["layer"]]
    bg = np.asarray(Image.open(d / layer["dark"]).convert("RGB").resize(A.FRAME, Image.BICUBIC), np.float32) / 0.45
    if layer["mask"]:
        m = np.asarray(Image.open(d / layer["mask"]).getchannel("A").resize(A.FRAME, Image.BILINEAR), np.float32) / 255
    else:
        m = np.zeros((A.FRAME[1], A.FRAME[0]), np.float32)
    return A.mode_at(bg, m, Placement(p["cx"], p["baseline"], p["size"]))


def editing() -> bool:
    return (paths.state() / "editing").exists()


def set_editing(on: bool) -> None:
    f = paths.state() / "editing"
    if on:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.touch()
    else:
        f.unlink(missing_ok=True)


def write_current(an: dict | None, error: str | None = None, wallpaper: str | None = None) -> dict:
    """What the clock draws. Paths are absolute so the QML needs no logic."""
    from depth_clock.geometry import font_name

    if an is None:
        cur = {"version": VERSION, "ready": False, "editing": editing(), "wallpaper": wallpaper or "", "error": error or ""}
    else:
        d = entry_dir(an["key"])
        p = resolve(an)
        cur = {
            "version": VERSION, "ready": True, "editing": editing(),
            "wallpaper": an["wallpaper"], "key": an["key"], "font": font_name(),
            "layer": p["layer"], "cx": p["cx"], "baseline": p["baseline"], "size": p["size"],
            "mode": resolved_mode(an, p), "modeSetting": p.get("mode", "auto"),
            "source": p["source"], "candidate": p.get("candidate"), "candidates": len(an["candidates"]),
            "layers": [{
                "mask": str(d / layer["mask"]) if layer["mask"] else "",
                "dark": str(d / layer["dark"]), "light": str(d / layer["light"]),
                "ridge": layer["ridge"], "peaks": layer["peaks"],
            } for layer in an["layers"]],
        }
    atomic_write(paths.current(), json.dumps(cur, indent=1))
    return cur
