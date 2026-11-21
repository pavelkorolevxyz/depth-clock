# Prototype of the analysis (seventh pass), kept for reference. The package in
# src/depth_clock is the maintained version; this one needs rembg for ISNet.
import sys, os, hashlib, numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage as ndi
import onnxruntime as ort

S = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(S, "out"); CACHE = os.path.join(S, "cache")
os.makedirs(OUT, exist_ok=True); os.makedirs(CACHE, exist_ok=True)
W, H = 1920, 1080
FONT = "/usr/share/fonts/noto/NotoSans-CondensedMedium.ttf"
TEXT = "14:25"

font = ImageFont.truetype(FONT, round(H * 0.3))
bb = font.getbbox(TEXT)
TW, GT, GB = bb[2] - bb[0], bb[1], bb[3]
GH = GB - GT
G = np.asarray((lambda g: (ImageDraw.Draw(g).text((-bb[0], -GT), TEXT, font=font, fill=255), g)[1])(Image.new("L", (TW, GH), 0)), np.float32) / 255
# Each character's columns, to check that every digit stays readable.
SPANS = []
for i, ch in enumerate(TEXT):
    if ch == ":": continue
    a = font.getbbox(TEXT[:i] + ch); b0 = font.getbbox(TEXT[:i]) if i else (bb[0],) * 4
    x1 = a[2] - bb[0]; x0 = (font.getlength(TEXT[:i])) - bb[0]
    SPANS.append((max(0, int(x0)), min(TW, int(x1))))

def load(path):
    im = Image.open(path).convert("RGB")
    s = max(W / im.width, H / im.height)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    l, t = (im.width - W) // 2, (im.height - H) // 2
    return im.crop((l, t, l + W, t + H))

def key(im, tag):
    return os.path.join(CACHE, hashlib.blake2b(im.tobytes(), digest_size=8).hexdigest() + "." + tag + ".npy")

_sess = {}
def depth(im, h=1036):
    k = key(im, f"depth{h}")
    if os.path.exists(k): return np.load(k)
    if "d" not in _sess:
        _sess["d"] = ort.InferenceSession(os.path.expanduser("~/.cache/depth-clock/models/depth-anything-v2-small.onnx"), providers=["CPUExecutionProvider"])
    s = _sess["d"]
    w = int(round(h * W / H / 14) * 14)
    x = (np.asarray(im.resize((w, h), Image.BICUBIC), np.float32) / 255 - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]
    d = s.run(None, {s.get_inputs()[0].name: x.transpose(2, 0, 1)[None].astype(np.float32)})[0].squeeze()
    d = (d - d.min()) / (d.max() - d.min() + 1e-6)
    d = np.asarray(Image.fromarray(d.astype(np.float32), "F").resize((W, H), Image.BICUBIC), np.float32)
    np.save(k, d); return d

def saliency(im):
    k = key(im, "sal")
    if os.path.exists(k): return np.load(k)
    from rembg import remove, new_session
    if "s" not in _sess: _sess["s"] = new_session("isnet-general-use")
    m = np.asarray(remove(im, session=_sess["s"], only_mask=True), np.float32) / 255
    np.save(k, m); return m

def box(a, r):
    c = np.pad(np.pad(a, r, mode="edge").cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    k = 2 * r + 1
    return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)

def guided(m, I, r=6, eps=2e-4):
    mI, mp = box(I, r), box(m, r)
    a = (box(I * m, r) - mI * mp) / (box(I * I, r) - mI * mI + eps)
    b = mp - a * mI
    return np.clip(box(a, r) * I + box(b, r), 0, 1)

def grounded(b):
    # Keep only parts that rest on the bottom edge: hills, buildings, people.
    # Logos, moons and clouds float and never go in front of the clock.
    lab, n = ndi.label(b)
    keep = np.unique(lab[-1][lab[-1] > 0])
    return np.isin(lab, keep)

def features(im):
    a = np.asarray(im, np.float32)
    L = a @ np.array([0.299, 0.587, 0.114], np.float32) / 255
    g = np.abs(np.diff(L, axis=0, prepend=L[:1])) + np.abs(np.diff(L, axis=1, prepend=L[:, :1]))
    detail = box(g, 4)
    global RAW
    RAW = detail
    # Relative to the picture itself: line art and grass are busy everywhere.
    detail = np.clip(detail / (np.quantile(detail, 0.9) + 1e-4), 0, 1.5)
    # Things that stand out from their surroundings: sun, moon, logos.
    outlier = np.clip((np.abs(L - box(L, 220)) - 0.2) * 3, 0, 1)
    return L, detail, outlier

def search(m, avoid, detail, L):
    best = None
    mb = m > 0.5
    for cx in np.linspace(0.28, 0.72, 12):
        x0 = int(W * cx - TW / 2)
        span = mb[:, x0:x0 + TW]
        for y0 in range(int(H * 0.06), int(H * 0.72) - GH, 6):
            mm = m[y0:y0 + GH, x0:x0 + TW]
            cov = (G * mm).sum() / G.sum()
            if not 0.12 <= cov <= 0.45: continue
            # Every digit at least 55% visible.
            if any((G[:, s0:s1] * mm[:, s0:s1]).sum() / (G[:, s0:s1].sum() + 1) > 0.45 for s0, s1 in SPANS): continue
            sb = span[y0:y0 + GH]
            has = sb.any(0)
            top = np.where(has, np.argmax(sb, 0), GH)
            # The occluder comes up from below: solid under its top edge.
            below = np.arange(GH)[:, None] >= top[None]
            fill = (sb & below).sum() / (below.sum() + 1)
            if fill < 0.8: continue
            # Digit tops stay visible: few columns covered to the very top.
            if (has & (top == 0)).mean() > 0.12: continue
            # The ridge must be a visible edge, not a seam only the model sees.
            cols = np.nonzero(has & (top > 6) & (top < GH - 6))[0]
            if len(cols) < 20: continue
            Lb = L[y0:y0 + GH, x0:x0 + TW]
            above = Lb[np.clip(top[cols] - 6, 0, GH - 1), cols]
            below = Lb[np.clip(top[cols] + 6, 0, GH - 1), cols]
            if np.abs(above - below).mean() < 0.05: continue
            rag = np.abs(np.diff(top / GH)).mean()
            vis = G * (1 - mm)
            clutter = (avoid[y0:y0 + GH, x0:x0 + TW] * vis).sum() / vis.sum()
            busy = (detail[y0:y0 + GH, x0:x0 + TW] * vis).sum() / vis.sum()
            Lv = Lb[vis > 0.5]
            uneven = Lv.std() if len(Lv) > 50 else 1
            spread = (np.percentile(Lv, 90) - np.percentile(Lv, 10)) if len(Lv) > 50 else 1
            raw = (RAW[y0:y0 + GH, x0:x0 + TW] * vis).sum() / vis.sum()
            score = (-abs(cov - 0.28) * 3 - rag * 25 - clutter * 6 - busy * 1.0
                     - (1 - fill) * 3 - uneven * 3 - spread * 4 - raw * 10 - abs(cx - 0.5) * 0.8 - (y0 / H) * 0.5)
            if best is None or score > best[0]:
                best = (score, x0, y0, dict(cov=cov, rag=rag, clutter=clutter, busy=busy, fill=fill))
    return best

def free_spot(avoid, detail, L):
    # No good occluder: the calmest place in the upper part of the screen.
    best = None
    for cx in np.linspace(0.2, 0.8, 13):
        x0 = int(W * cx - TW / 2)
        for y0 in range(int(H * 0.08), int(H * 0.6) - GH, 10):
            r = (slice(y0, y0 + GH), slice(x0, x0 + TW))
            Lv = L[r][G > 0.5]
            s = -(avoid[r] * G).sum() / G.sum() * 15 - (detail[r] * G).sum() / G.sum() * 2.5 - Lv.std() * 10 - (np.percentile(Lv, 90) - np.percentile(Lv, 10)) * 4 - (RAW[r] * G).sum() / G.sum() * 10 - abs(cx - 0.5) * 0.8 - abs(y0 / H - 0.25) * 0.6
            if best is None or s > best[0]: best = (s, x0, y0)
    return best

def lum(c): return float(c @ [0.299, 0.587, 0.114]) + 1e-3

def colors(a, m, x0, y0):
    # The color follows the background behind each part of the digits:
    # blur the sky with the occluders left out, then darken or lift it.
    pad = 80
    ys, xs = slice(max(0, y0 - pad), min(H, y0 + GH + pad)), slice(max(0, x0 - pad), min(W, x0 + TW + pad))
    reg = a[ys, xs]; w = (m[ys, xs] < 0.5).astype(np.float32)
    r = 40
    num = np.stack([box(reg[..., c] * w, r) for c in range(3)], -1)
    den = box(w, r)[..., None] + 1e-4
    bg = num / den
    oy, ox = y0 - ys.start, x0 - xs.start
    bg = bg[oy:oy + GH, ox:ox + TW]
    Lb = bg @ np.array([0.299, 0.587, 0.114], np.float32) + 1e-3
    vis = (G > 0.3) & (m[y0:y0 + GH, x0:x0 + TW] < 0.5)
    Ls = float(np.median(Lb[vis])) if vis.sum() > 50 else float(np.median(Lb))
    p10 = float(np.percentile(Lb[vis], 10)) if vis.sum() > 50 else Ls
    if Ls >= 28 and p10 >= 20:
        return np.clip(bg * 0.45, 0, 255), "dark", Ls
    hi = np.quantile(a.reshape(-1, 3), 0.985, axis=0)
    target = Lb + 70
    t = np.clip((target - Lb) / (lum(hi) - Lb + 1e-3), 0, 1)[..., None]
    out = bg + (hi - bg) * t
    out = out * np.maximum(1.0, target / (out @ np.array([0.299, 0.587, 0.114], np.float32) + 1e-3))[..., None]
    return np.clip(out, 0, 255), "light", Ls

def render(im, m, x0, y0, label):
    a = np.asarray(im, np.float32)
    rows, mode, Ls = colors(a, m, x0, y0)
    mode = f"{mode} Ls={Ls:.0f}"
    out = a.copy()
    grad = rows
    r = (slice(y0, y0 + GH), slice(x0, x0 + TW))
    reg = out[r]
    g = G[..., None]; mm = m[r][..., None]
    reg[:] = reg * (1 - g) + grad * g
    reg[:] = reg * (1 - mm) + a[r] * mm
    full = Image.fromarray(out.astype(np.uint8))
    return full, mode

def run(path):
    name = os.path.splitext(os.path.basename(path))[0]
    im = load(path)
    d = depth(im); sal = saliency(im)
    if sal.mean() > 0.35: sal = np.zeros_like(sal)
    L, detail, outlier = features(im)
    best = None
    for q in np.linspace(0.1, 0.85, 16):
        t = np.quantile(d, q)
        b = grounded(d > t)
        b = ndi.binary_opening(b, iterations=2)
        if b.mean() < 0.05: continue
        m = guided(b.astype(np.float32), L)
        # Don't cover salient things that are not themselves in front.
        avoid = np.maximum(sal * (1 - m), outlier * (1 - m))
        p = search(m, avoid, detail, L)
        if p and (best is None or p[0] > best[0][0]): best = (p, m, q)
    if best is None or best[0][0] < -3.0:
        avoid = np.maximum(sal, outlier)
        s, x0, y0 = free_spot(avoid, detail, L)
        m = np.zeros((H, W), np.float32)
        label = f"free (best={best[0][0]:.2f})" if best else "free"
    else:
        (score, x0, y0, info), m, q = best
        label = f"q={q:.2f} s={score:.2f} cov={info['cov']:.2f}"
    full, mode = render(im, m, x0, y0, label)
    full.save(os.path.join(OUT, name + ".full.png"))
    Image.fromarray((m * 255).astype(np.uint8)).save(os.path.join(OUT, name + ".mask.png"))
    t = full.resize((W // 3, H // 3), Image.LANCZOS)
    dr = ImageDraw.Draw(t); lab = f"{name}  {mode}  {label}"
    dr.rectangle((0, 0, 7 * len(lab) + 10, 16), fill=(0, 0, 0))
    dr.text((4, 2), lab, fill=(255, 255, 255), font=ImageFont.truetype(FONT, 12))
    return name, t, (x0, y0)

if __name__ == "__main__":
    tiles = []
    for p in sys.argv[1:]:
        name, t, pos = run(p); tiles.append(t); print(name, pos, flush=True)
    cols = 4
    for k in range(0, len(tiles), 12):
        part = tiles[k:k + 12]; rows = (len(part) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * (W // 3 + 4), rows * (H // 3 + 4)), (20, 20, 20))
        for i, t in enumerate(part): sheet.paste(t, ((i % cols) * (W // 3 + 4), (i // cols) * (H // 3 + 4)))
        sheet.save(os.path.join(OUT, f"sheet{k // 12 + 1}.jpg"), quality=86)
