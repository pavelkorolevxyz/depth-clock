"""Find what can stand in front of the clock, and where the clock looks good.

The steps, for one wallpaper:
1. Relative depth from a model. Cut it at several depths: each cut is a layer,
   what is nearer than the cut stands in front of the clock. Keep only parts
   that rest on the bottom edge, so logos, moons and clouds never do.
2. For each layer, try places for the clock. A good place has about a third of
   the digits covered, every digit readable, a visible ridge, a calm even
   background behind the visible part, and nothing important under the digits.
3. If nothing is good, place the clock alone on the calmest spot.
4. Color follows the background behind each part of the digits: half its
   brightness on light skies, lifted toward the picture's highlights on dark ones.
"""

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

from depth_clock.geometry import Glyphs, Placement, glyphs

FRAME = (1920, 1080)  # analysis size
MASK_SIZE = (2560, 1440)  # mask files: sharp on the largest common screen
TINT_SIZE = (960, 540)  # tint files: blurred anyway
SIZE = 0.30  # default font size, of the height
ACCEPT = -3.0  # below this score, the clock goes without anything in front
LUMA = np.array([0.299, 0.587, 0.114], np.float32)


def load_frame(path, size=FRAME) -> Image.Image:
    """The wallpaper as the screen shows it: scaled to cover, center crop."""
    im = Image.open(path).convert("RGB")
    W, H = size
    s = max(W / im.width, H / im.height)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    left, top = (im.width - W) // 2, (im.height - H) // 2
    return im.crop((left, top, left + W, top + H))


def box(a: np.ndarray, r: int) -> np.ndarray:
    c = np.pad(np.pad(a, r, mode="edge").cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    k = 2 * r + 1
    return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)


def guided(m: np.ndarray, guide: np.ndarray, r: int = 6, eps: float = 2e-4) -> np.ndarray:
    """Snap a coarse mask to the edges of the picture."""
    mI, mp = box(guide, r), box(m, r)
    a = (box(guide * m, r) - mI * mp) / (box(guide * guide, r) - mI * mI + eps)
    b = mp - a * mI
    return np.clip(box(a, r) * guide + box(b, r), 0, 1)


def grounded(b: np.ndarray) -> np.ndarray:
    """Keep the parts that touch the bottom edge."""
    lab, _ = ndi.label(b)
    keep = np.unique(lab[-1][lab[-1] > 0])
    return np.isin(lab, keep)


def luma(a: np.ndarray) -> np.ndarray:
    return a @ LUMA


class Picture:
    """The wallpaper at analysis size and the maps the search scores with."""

    def __init__(self, img: Image.Image, depth: np.ndarray | None, subject: np.ndarray):
        self.img = img
        self.rgb = np.asarray(img, np.float32)
        self.H, self.W = self.rgb.shape[:2]
        self.L = luma(self.rgb) / 255
        self.depth = depth
        g = np.abs(np.diff(self.L, axis=0, prepend=self.L[:1])) + np.abs(np.diff(self.L, axis=1, prepend=self.L[:, :1]))
        self.raw = box(g, 4)  # absolute detail: grass, line art
        self.detail = np.clip(self.raw / (np.quantile(self.raw, 0.9) + 1e-4), 0, 1.5)  # relative to this picture
        self.outlier = np.clip((np.abs(self.L - box(self.L, 220)) - 0.2) * 3, 0, 1)  # sun, moon, logos
        # A subject that fills most of the picture says nothing about where not to go.
        self.subject = subject if subject.mean() <= 0.35 else np.zeros_like(subject)


def layers_from_depth(pic: Picture, steps: int = 16) -> list[np.ndarray]:
    """Distinct soft masks, far cut first."""
    out, last = [], None
    for q in np.linspace(0.1, 0.85, steps):
        b = grounded(pic.depth > np.quantile(pic.depth, q))
        b = ndi.binary_opening(b, iterations=2)
        if not 0.05 <= b.mean() <= 0.9:
            continue
        if last is not None and (b & last).sum() / max((b | last).sum(), 1) > 0.92:
            continue
        last = b
        out.append(guided(b.astype(np.float32), pic.L))
    return out


def search(pic: Picture, m: np.ndarray, g: Glyphs) -> list[tuple]:
    """Every acceptable place for the clock behind this layer, scored."""
    W, H, G, GH, TW = pic.W, pic.H, g.alpha, g.h, g.w
    mb = m > 0.5
    avoid = np.maximum(pic.subject, pic.outlier) * (1 - m)
    gsum = G.sum()
    rows = np.arange(GH)[:, None]
    found = []
    for cx in np.linspace(0.28, 0.72, 12):
        x0 = int(W * cx - TW / 2)
        if x0 < 0 or x0 + TW > W:
            continue
        span = mb[:, x0:x0 + TW]
        for y0 in range(int(H * 0.06), int(H * 0.72) - GH, 6):
            mm = m[y0:y0 + GH, x0:x0 + TW]
            cov = (G * mm).sum() / gsum
            if not 0.12 <= cov <= 0.45:
                continue
            # Every digit at least 55% visible.
            if any((G[:, a:b] * mm[:, a:b]).sum() / (G[:, a:b].sum() + 1) > 0.45 for a, b in g.spans):
                continue
            sb = span[y0:y0 + GH]
            has = sb.any(0)
            top = np.where(has, np.argmax(sb, 0), GH)
            # The occluder comes up from below and is solid under its edge.
            below = rows >= top[None]
            fill = (sb & below).sum() / (below.sum() + 1)
            if fill < 0.8:
                continue
            # The tops of the digits stay visible.
            if (has & (top == 0)).mean() > 0.12:
                continue
            # The ridge is a visible edge, not a seam only the model sees.
            cols = np.nonzero(has & (top > 6) & (top < GH - 6))[0]
            if len(cols) < 20:
                continue
            Lb = pic.L[y0:y0 + GH, x0:x0 + TW]
            above = Lb[np.clip(top[cols] - 6, 0, GH - 1), cols]
            under = Lb[np.clip(top[cols] + 6, 0, GH - 1), cols]
            if np.abs(above - under).mean() < 0.05:
                continue
            rag = np.abs(np.diff(top / GH)).mean()
            vis = G * (1 - mm)
            vsum = vis.sum()
            clutter = (avoid[y0:y0 + GH, x0:x0 + TW] * vis).sum() / vsum
            busy = (pic.detail[y0:y0 + GH, x0:x0 + TW] * vis).sum() / vsum
            raw = (pic.raw[y0:y0 + GH, x0:x0 + TW] * vis).sum() / vsum
            Lv = Lb[vis > 0.5]
            uneven = Lv.std() if len(Lv) > 50 else 1
            spread = (np.percentile(Lv, 90) - np.percentile(Lv, 10)) if len(Lv) > 50 else 1
            score = (-abs(cov - 0.28) * 3 - rag * 25 - clutter * 6 - busy * 1.0 - (1 - fill) * 3
                     - uneven * 3 - spread * 4 - raw * 10 - abs(cx - 0.5) * 0.8 - (y0 / H) * 0.5)
            found.append((score, x0, y0))
    return found


def free_spots(pic: Picture, g: Glyphs) -> list[tuple]:
    """Places for the clock with nothing in front: calm, even, off the subject."""
    W, H, G, GH, TW = pic.W, pic.H, g.alpha, g.h, g.w
    avoid = np.maximum(pic.subject, pic.outlier)
    gsum = G.sum()
    found = []
    for cx in np.linspace(0.2, 0.8, 13):
        x0 = int(W * cx - TW / 2)
        if x0 < 0 or x0 + TW > W:
            continue
        for y0 in range(int(H * 0.08), int(H * 0.6) - GH, 10):
            r = (slice(y0, y0 + GH), slice(x0, x0 + TW))
            Lv = pic.L[r][G > 0.5]
            s = (-(avoid[r] * G).sum() / gsum * 15 - (pic.detail[r] * G).sum() / gsum * 2.5 - Lv.std() * 10
                 - (np.percentile(Lv, 90) - np.percentile(Lv, 10)) * 4 - (pic.raw[r] * G).sum() / gsum * 10
                 - abs(cx - 0.5) * 0.8 - abs(y0 / H - 0.25) * 0.6)
            found.append((s, x0, y0))
    return found


def distinct(cands: list[tuple], W: int, H: int, limit: int) -> list[tuple]:
    """Best first, dropping places too close to a better one."""
    out = []
    for c in sorted(cands, key=lambda c: -c[0]):
        if all(abs(c[-2] - o[-2]) > 0.1 * W or abs(c[-1] - o[-1]) > 0.08 * H for o in out):
            out.append(c)
            if len(out) == limit:
                break
    return out


def background(pic: Picture, m: np.ndarray, r: int = 40) -> np.ndarray:
    """The sky behind the occluders: a blur that leaves them out."""
    w = (m < 0.5).astype(np.float32)
    num = np.stack([box(pic.rgb[..., c] * w, r) for c in range(3)], -1)
    den = box(w, r)[..., None]
    plain = np.stack([box(pic.rgb[..., c], r) for c in range(3)], -1)
    return np.where(den > 0.02, num / np.maximum(den, 1e-4), plain)


def tints(pic: Picture, bg: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Digit colors for every point: a dark silhouette and a lifted light tone."""
    dark = bg * 0.45
    Lb = luma(bg) + 1e-3
    hi = np.quantile(pic.rgb.reshape(-1, 3), 0.985, axis=0)
    target = Lb + 70
    t = np.clip((target - Lb) / (float(hi @ LUMA) - Lb + 1e-3), 0, 1)[..., None]
    light = bg + (hi - bg) * t
    light = light * np.maximum(1.0, target / (luma(light) + 1e-3))[..., None]
    return np.clip(dark, 0, 255), np.clip(light, 0, 255)


def mode_at(bg: np.ndarray, m: np.ndarray, p: Placement) -> str:
    """Dark digits where the sky behind them is light enough everywhere."""
    H, W = bg.shape[:2]
    g = glyphs(max(8, round(p.size * H)))
    x0, y0 = g.ink_origin(p, W, H)
    xs, ys = slice(max(0, x0), min(W, x0 + g.w)), slice(max(0, y0), min(H, y0 + g.h))
    G = g.alpha[ys.start - y0:ys.stop - y0, xs.start - x0:xs.stop - x0]
    Lb = luma(bg[ys, xs])
    vis = (G > 0.3) & (m[ys, xs] < 0.5)
    if vis.sum() < 50:
        vis = G > 0.3
    if vis.sum() < 50:
        return "dark"
    Ls, p10 = float(np.median(Lb[vis])), float(np.percentile(Lb[vis], 10))
    return "dark" if Ls >= 28 and p10 >= 20 else "light"


def ridge(m: np.ndarray, samples: int = 240) -> tuple[list[float], list[dict]]:
    """The top edge of a layer by column, and its highest peaks, as fractions."""
    H, W = m.shape
    cols = np.linspace(0, W - 1, samples).astype(int)
    mb = m[:, cols] > 0.5
    has = mb.any(0)
    top = np.where(has, np.argmax(mb, 0), H) / H
    smooth = np.convolve(np.pad(top, 2, mode="edge"), np.ones(5) / 5, "valid")
    peaks = []
    for i in np.argsort(smooth):
        if smooth[i] >= 0.98:
            break
        lo, hi = max(0, i - 15), min(samples, i + 16)
        if smooth[i] > smooth[lo:hi].min() + 1e-6:
            continue  # not the highest point around
        x = i / (samples - 1)
        if all(abs(x - p["x"]) > 0.08 for p in peaks):
            peaks.append({"x": round(x, 4), "y": round(float(smooth[i]), 4)})
        if len(peaks) == 3:
            break
    return [round(float(v), 4) for v in top], peaks


def analyze(img: Image.Image, depth: np.ndarray | None, subject: np.ndarray, manual: np.ndarray | None = None) -> dict:
    """Layers and ranked placements. Masks and tints come back as arrays."""
    pic = Picture(img, depth, subject)
    g = glyphs(round(SIZE * pic.H))
    masks = [manual] if manual is not None else layers_from_depth(pic)

    layers = [{"mask": None}]  # layer 0: nothing in front
    behind = []
    for i, m in enumerate(masks, start=1):
        layers.append({"mask": m})
        behind += [(s, i, x0, y0) for s, x0, y0 in search(pic, m, g)]
    good = [c for c in distinct(behind, pic.W, pic.H, 10) if c[0] >= ACCEPT]
    free = [(s, 0, x0, y0) for s, x0, y0 in distinct(free_spots(pic, g), pic.W, pic.H, 3)]

    for layer in layers:
        m = layer["mask"] if layer["mask"] is not None else np.zeros((pic.H, pic.W), np.float32)
        layer["bg"] = background(pic, m)
        layer["dark"], layer["light"] = tints(pic, layer["bg"])
        layer["ridge"], layer["peaks"] = ridge(m) if layer["mask"] is not None else ([], [])

    candidates = []
    for s, i, x0, y0 in good + free:
        p = g.placement(x0, y0, pic.W, pic.H, SIZE)
        m = layers[i]["mask"] if i else np.zeros((pic.H, pic.W), np.float32)
        candidates.append({
            "layer": i, "cx": round(p.cx, 4), "baseline": round(p.baseline, 4), "size": SIZE,
            "mode": mode_at(layers[i]["bg"], m, p), "score": round(float(s), 3),
            "kind": "behind" if i else "free",
        })
    return {"layers": layers, "candidates": candidates}


def mask_image(m: np.ndarray, guide: Image.Image) -> Image.Image:
    """A layer as the clock reads it: white, opaque over the occluders, at mask size."""
    W, H = MASK_SIZE
    up = np.asarray(Image.fromarray(m.astype(np.float32), "F").resize((W, H), Image.BICUBIC), np.float32).clip(0, 1)
    L = np.asarray(guide.resize((W, H), Image.LANCZOS).convert("L"), np.float32) / 255
    a = guided(up, L, r=8)
    out = np.zeros((H, W, 4), np.uint8)
    out[..., :3] = 255
    out[..., 3] = (a * 255).round().astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def tint_image(t: np.ndarray) -> Image.Image:
    return Image.fromarray(t.round().astype(np.uint8)).resize(TINT_SIZE, Image.LANCZOS)
