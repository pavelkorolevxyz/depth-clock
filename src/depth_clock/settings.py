"""~/.config/depth-clock/config.json, all fields optional:

  wallpaper  the image to follow, or a symlink to it (see wallpaper.py)
  font       font family for the digits, as fontconfig names it
"""

import json

from depth_clock import paths


def load() -> dict:
    try:
        data = json.loads(paths.settings().read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
