"""The analysis on synthetic pictures, without the models."""

import json

import numpy as np
import pytest
from PIL import Image

from depth_clock import analyze as A
from depth_clock import geometry, store

W, H = A.FRAME

try:
    geometry.font_file("serif")
except RuntimeError:
    pytest.skip("fontconfig has no serif font", allow_module_level=True)


def scene(sky=(190, 170, 210), ground=(40, 30, 60)):
    """Sky over a jagged ridge, and a bright disc floating in the sky."""
    x = np.arange(W)
    ridge = (0.5 + 0.06 * np.sin(x / 70) + 0.03 * np.sin(x / 23)) * H
    yy = np.arange(H)[:, None]
    rock = yy >= ridge[None]
    rgb = np.empty((H, W, 3), np.float32)
    rgb[:] = sky
    rgb[rock] = ground
    disc = (yy - 0.2 * H) ** 2 + (x[None] - 0.8 * W) ** 2 < 60 ** 2
    rgb[disc] = (255, 250, 230)
    depth = np.where(rock, 0.9, 0.1).astype(np.float32)
    depth[disc] = 0.95  # the model calls it near; it must not stand in front
    return Image.fromarray(rgb.astype(np.uint8)), depth, rock


def test_grounded_drops_floating_parts():
    b = np.zeros((100, 100), bool)
    b[80:, :] = True     # ground
    b[10:20, 40:60] = True  # floating
    g = A.grounded(b)
    assert g[90, 50] and not g[15, 50]


def test_placement_round_trip():
    g = geometry.glyphs(324)
    p = geometry.Placement(0.53, 0.47, 0.3)
    x0, y0 = g.ink_origin(p, W, H)
    q = g.placement(x0, y0, W, H, 0.3)
    assert abs(q.cx - p.cx) < 1 / W and abs(q.baseline - p.baseline) < 1 / H


def test_clock_goes_behind_the_ridge_not_the_disc():
    img, depth, rock = scene()
    res = A.analyze(img, depth, np.zeros((H, W), np.float32))
    assert len(res["layers"]) >= 2
    for layer in res["layers"][1:]:
        assert layer["mask"][int(0.2 * H), int(0.8 * W)] < 0.5  # the disc never occludes
    best = res["candidates"][0]
    assert best["kind"] == "behind"
    # A part of the digits is covered, and the clock is above the bottom of the ridge.
    g = geometry.glyphs(round(A.SIZE * H))
    x0, y0 = g.ink_origin(geometry.Placement(best["cx"], best["baseline"], best["size"]), W, H)
    covered = (g.alpha * rock[y0:y0 + g.h, x0:x0 + g.w]).sum() / g.alpha.sum()
    assert 0.1 < covered < 0.5
    assert best["mode"] == "dark"


def test_light_digits_on_a_dark_sky():
    img, depth, _ = scene(sky=(14, 12, 22), ground=(70, 60, 90))
    res = A.analyze(img, depth, np.zeros((H, W), np.float32))
    assert res["candidates"][0]["mode"] == "light"


def test_free_clock_without_any_ground():
    img = Image.new("RGB", (W, H), (120, 140, 170))
    depth = np.zeros((H, W), np.float32)
    res = A.analyze(img, depth, np.zeros((H, W), np.float32))
    assert len(res["layers"]) == 1
    assert res["candidates"] and all(c["kind"] == "free" for c in res["candidates"])


def test_ridge_peaks_are_the_highest_points():
    m = np.zeros((H, W), np.float32)
    x = np.arange(W)
    top = (0.6 - 0.2 * np.exp(-((x - 0.3 * W) / 60) ** 2) - 0.1 * np.exp(-((x - 0.75 * W) / 60) ** 2)) * H
    m[np.arange(H)[:, None] >= top[None]] = 1
    ridge, peaks = A.ridge(m)
    assert len(ridge) == 240
    assert abs(peaks[0]["x"] - 0.3) < 0.01 and abs(peaks[1]["x"] - 0.75) < 0.01


def test_user_placement_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    an = {"key": "k", "candidates": [{"layer": 1, "cx": 0.5, "baseline": 0.5, "size": 0.3, "mode": "dark"}]}
    assert store.resolve(an)["source"] == "auto"
    store.save_placement("k", {"layer": 0, "cx": 0.4, "baseline": 0.3, "size": 0.2, "mode": "light"})
    p = store.resolve(an)
    assert p["source"] == "user" and p["cx"] == 0.4
    assert json.loads((tmp_path / "config/depth-clock/placements.json").read_text())["k"]["layer"] == 0
    store.save_placement("k", None)
    assert store.resolve(an)["source"] == "auto"


def test_wallpaper_lookup_order(tmp_path, monkeypatch):
    from depth_clock import wallpaper

    a, b, c = (tmp_path / f"{n}.png" for n in "abc")
    for f in (a, b, c):
        f.write_bytes(b"x")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("DEPTH_CLOCK_WALLPAPER", raising=False)
    monkeypatch.setattr(wallpaper, "DETECTORS", [("test", lambda: c)])
    assert wallpaper.find() == c
    conf = tmp_path / "config/depth-clock/config.json"
    conf.parent.mkdir(parents=True)
    conf.write_text(json.dumps({"wallpaper": str(b)}))
    assert wallpaper.find() == b
    monkeypatch.setenv("DEPTH_CLOCK_WALLPAPER", str(a))
    assert wallpaper.find() == a
    assert wallpaper.find(str(c)) == c


def test_font_comes_from_config_and_must_exist(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert geometry.font_family() == geometry.DEFAULT_FONT
    (tmp_path / "depth-clock").mkdir()
    (tmp_path / "depth-clock/config.json").write_text(json.dumps({"font": "No Such Font Family 123"}))
    assert geometry.font_family() == "No Such Font Family 123"
    with pytest.raises(RuntimeError):
        geometry.font_file("No Such Font Family 123")
    # Each font gets its own analysis cache.
    with pytest.raises(RuntimeError):
        store.entry_dir("k")
    # A generic name resolves to a real font, which names the cache.
    (tmp_path / "depth-clock/config.json").write_text(json.dumps({"font": "serif"}))
    name = geometry.font_name()
    assert name and name.lower() != "serif"
    assert store.entry_dir("k").name.endswith(name.lower().replace(" ", "-"))
