"""Render the clock on the wallpaper offline, the way the clock draws it."""

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from depth_clock import analyze as A
from depth_clock import store
from depth_clock.geometry import font_file


def render(an: dict, p: dict, text: str = "14:25", size=A.FRAME) -> Image.Image:
    W, H = size
    d = store.entry_dir(an["key"])
    layer = an["layers"][p["layer"]]
    mode = store.resolved_mode(an, p)
    wall = np.asarray(A.load_frame(an["wallpaper"], size), np.float32)
    tint = np.asarray(Image.open(d / layer[mode]).convert("RGB").resize(size, Image.BICUBIC), np.float32)
    font = ImageFont.truetype(font_file(), round(p["size"] * H))
    alpha = Image.new("L", size, 0)
    x = p["cx"] * W - font.getlength(text) / 2
    ImageDraw.Draw(alpha).text((x, p["baseline"] * H), text, font=font, fill=255, anchor="ls")
    a = np.asarray(alpha, np.float32)[..., None] / 255
    out = wall * (1 - a) + tint * a
    if layer["mask"]:
        m = np.asarray(Image.open(d / layer["mask"]).getchannel("A").resize(size, Image.BILINEAR), np.float32)[..., None] / 255
        out = out * (1 - m) + wall * m
    return Image.fromarray(out.round().astype(np.uint8))
