# Mountain mask for a wallpaper: opaque over the ridge and below, by column.
# usage: python3 mask.py <rgb raw> <W> <H> <out gray raw> [bright] [dark] [slope]
import sys, numpy as np
from numpy.lib.stride_tricks import sliding_window_view
src, W, H, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
bright = float(sys.argv[5]) if len(sys.argv) > 5 else 11
dark = float(sys.argv[6]) if len(sys.argv) > 6 else 5
slope = float(sys.argv[7]) if len(sys.argv) > 7 else 0.62
a = np.fromfile(src, np.uint8).reshape(H, W, 3).astype(np.float32)
L = a.mean(axis=2)
k = 5
pad = np.pad(L, ((k // 2, k // 2), (k // 2, k // 2)), mode="edge")
c = np.pad(np.cumsum(np.cumsum(pad, 0), 1), ((1, 0), (1, 0)))
B = (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)
y0, y1 = int(H * 0.32), int(H * 0.65)
dark_from = int(H * 0.12)
sky = np.full(W, y1, float)
for x in range(W):
    run = np.median(B[y0 - int(H * 0.07):y0, x])
    for i, v in enumerate(B[y0:y1, x]):
        # Darker-than-sky only counts low in the band: higher up it is a cloud.
        if v > run + bright or (i > dark_from and v < run - dark):
            sky[x] = y0 + i
            break
        run = 0.97 * run + 0.03 * v
r = 7
sky = np.median(sliding_window_view(np.pad(sky, (r, r), mode="edge"), 2 * r + 1), axis=1)
# A column far above its wide neighbourhood is a cloud, not a peak.
R = 90
wide = np.median(sliding_window_view(np.pad(sky, (R, R), mode="edge"), 2 * R + 1), axis=1)
sky = np.where(sky < wide - 0.09 * H, wide, sky)
for x in range(1, W): sky[x] = min(sky[x], sky[x - 1] + slope)
for x in range(W - 2, -1, -1): sky[x] = min(sky[x], sky[x + 1] + slope)
np.save(out + ".npy", sky)
yy = np.arange(H)[:, None]
((np.clip((yy - sky[None, :] + 1.5) / 3.0, 0, 1)) * 255).astype(np.uint8).tofile(out)
