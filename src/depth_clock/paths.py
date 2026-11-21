"""Where things live, following the XDG base directories."""

import os
from pathlib import Path


def _xdg(var: str, default: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / default)


def cache() -> Path:
    return _xdg("XDG_CACHE_HOME", ".cache") / "depth-clock"


def models() -> Path:
    return cache() / "models"


def config() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / "depth-clock"


def state() -> Path:
    return _xdg("XDG_STATE_HOME", ".local/state") / "depth-clock"


def current() -> Path:
    """What the clock reads: the clock for the current wallpaper."""
    return state() / "current.json"


def placements() -> Path:
    """Placements the user chose, by wallpaper."""
    return config() / "placements.json"


def mask_dirs() -> list[Path]:
    """Hand-made masks, by wallpaper name."""
    return [config() / "masks"]


def settings() -> Path:
    """Optional settings, such as where to find the wallpaper."""
    return config() / "config.json"
