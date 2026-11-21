"""Which image is the wallpaper now.

Tried in order, first match wins:
  1. --wallpaper on the command line
  2. DEPTH_CLOCK_WALLPAPER in the environment
  3. "wallpaper" in ~/.config/depth-clock/config.json: a file, or a symlink
     your wallpaper setter keeps pointing at the current image
  4. what a known wallpaper setter reports (see DETECTORS)
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

from depth_clock import paths


def _link(path: str):
    p = Path(path).expanduser()
    return p.resolve() if p.exists() else None


def _swww():
    if not shutil.which("swww"):
        return None
    out = subprocess.run(["swww", "query"], capture_output=True, text=True, timeout=2).stdout
    for line in out.splitlines():
        if "image: " in line:
            return _link(line.split("image: ", 1)[1].strip())
    return None


# Each returns a path or None. Add one for your setter.
DETECTORS = [
    ("omarchy", lambda: _link("~/.local/state/omarchy/current/background")),
    ("swww", _swww),
]


def find(arg: str | None = None) -> Path | None:
    for src in (arg, os.environ.get("DEPTH_CLOCK_WALLPAPER")):
        if src:
            return _link(src)
    try:
        conf = json.loads(paths.settings().read_text())
    except (OSError, ValueError):
        conf = {}
    if conf.get("wallpaper"):
        return _link(conf["wallpaper"])
    for _, detect in DETECTORS:
        try:
            found = detect()
        except (OSError, subprocess.SubprocessError):
            found = None
        if found and found.is_file():
            return found
    return None
