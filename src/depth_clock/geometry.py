"""Where the digits are, in the units both the analysis and the clock use.

A placement is three fractions of the screen:
  cx        the horizontal center of the text's advance box, of the width
  baseline  the text baseline, of the height
  size      the font pixel size, of the height
The clock draws one Text item from the same font, so the two agree.
"""

import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFont

DEFAULT_FONT = "serif"  # fontconfig's default serif, whatever the system has
GENERIC = {"serif", "sans-serif", "sans", "monospace"}
SAMPLE = "14:25"


def font_family() -> str:
    """The font from config.json ("font"), or the default."""
    from depth_clock import settings

    return settings.load().get("font") or DEFAULT_FONT


@lru_cache(maxsize=8)
def _match(family: str) -> tuple[str, str]:
    """(file, name) of the font fontconfig picks for a family name.

    A generic name (serif, sans-serif, monospace) takes whatever the system
    maps it to, and the name is that font's family. Any other name must match a
    font that is installed: fontconfig always answers with something.
    """
    if shutil.which("fc-match"):
        out = subprocess.run(["fc-match", "-f", "%{file}\n%{family}\n%{fullname}", family], capture_output=True, text=True)
        lines = out.stdout.split("\n")
        if out.returncode == 0 and len(lines) >= 3 and lines[0]:
            families = [n.strip() for n in lines[1].split(",") if n.strip()]
            if family.lower() in GENERIC and families:
                return lines[0], families[0]
            names = {n.lower() for n in families} | {n.strip().lower() for n in lines[2].split(",")}
            if family.lower() in names:
                return lines[0], family
    raise RuntimeError(f"font not found: {family}")


def font_file(family: str | None = None) -> str:
    return _match(family or font_family())[0]


def font_name(family: str | None = None) -> str:
    """The name Quickshell draws with, and the analysis cache is keyed by."""
    return _match(family or font_family())[1]


@dataclass(frozen=True)
class Placement:
    cx: float
    baseline: float
    size: float


class Glyphs:
    """The sample time rendered once: its alpha, ink box and digit columns."""

    def __init__(self, px: int, family: str, text: str = SAMPLE):
        font = ImageFont.truetype(font_file(family), px)
        self.px = px
        self.advance = font.getlength(text)
        left, top, right, bottom = font.getbbox(text, anchor="ls")
        self.ink = (left, top, right, bottom)  # relative to (left edge, baseline)
        self.w, self.h = right - left, bottom - top
        img = Image.new("L", (self.w, self.h), 0)
        ImageDraw.Draw(img).text((-left, -top), text, font=font, fill=255, anchor="ls")
        self.alpha = np.asarray(img, np.float32) / 255
        # Columns of each digit inside the ink box, to keep every digit readable.
        self.spans = []
        for i, ch in enumerate(text):
            if not ch.isdigit():
                continue
            x0 = font.getlength(text[:i]) - left
            x1 = font.getbbox(text[: i + 1], anchor="ls")[2] - left
            self.spans.append((max(0, int(x0)), min(self.w, int(x1))))

    def ink_origin(self, p: Placement, W: int, H: int) -> tuple[int, int]:
        """Top-left of the ink box in pixels."""
        left = p.cx * W - self.advance / 2
        return round(left + self.ink[0]), round(p.baseline * H + self.ink[1])

    def placement(self, x0: int, y0: int, W: int, H: int, size: float) -> Placement:
        left = x0 - self.ink[0]
        return Placement((left + self.advance / 2) / W, (y0 - self.ink[1]) / H, size)


@lru_cache(maxsize=8)
def _glyphs(px: int, family: str) -> Glyphs:
    return Glyphs(px, family)


def glyphs(px: int, family: str | None = None) -> Glyphs:
    return _glyphs(px, family or font_family())
