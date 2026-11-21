"""depth-clock: a desktop clock set behind the foreground of the wallpaper."""

import argparse
import json
import sys
from pathlib import Path

from depth_clock import paths, store, wallpaper


def current_wallpaper(arg: str | None) -> Path:
    p = wallpaper.find(arg)
    if p is None or not p.is_file():
        raise SystemExit("depth-clock: wallpaper not found; pass --wallpaper, set DEPTH_CLOCK_WALLPAPER,"
                         f" or put \"wallpaper\" in {paths.settings()}")
    return p


def loaded(args) -> dict:
    return store.analysis(current_wallpaper(getattr(args, "wallpaper", None)))


def publish(an: dict, quiet: bool = False) -> dict:
    cur = store.write_current(an)
    if not quiet:
        describe(cur)
    return cur


def describe(cur: dict) -> None:
    if not cur.get("ready"):
        print(f"not ready: {cur.get('error') or 'no analysis'}")
        return
    layer = "nothing in front" if cur["layer"] == 0 else f"layer {cur['layer']} of {len(cur['layers']) - 1}"
    where = f"x {cur['cx']:.3f}  baseline {cur['baseline']:.3f}  size {cur['size']:.3f}"
    pick = f"place {cur['candidate'] + 1} of {cur['candidates']}" if cur.get("candidate") is not None else "custom place"
    print(f"{Path(cur['wallpaper']).name}: {layer}, {cur['mode']} digits, {pick} ({cur['source']})")
    print(where)


def cmd_sync(args):
    try:
        an = loaded(args)
    except SystemExit:
        raise
    except Exception as e:  # keep the clock informed instead of leaving it stale
        store.write_current(None, error=str(e), wallpaper=args.wallpaper)
        raise
    publish(an, args.quiet)


def cmd_analyze(args):
    an = store.analysis(current_wallpaper(args.wallpaper), force=args.force)
    if args.json:
        print(json.dumps(an, indent=1))
    else:
        print(f"{len(an['layers']) - 1} layers, {len(an['candidates'])} places")
        for i, c in enumerate(an["candidates"]):
            print(f"  {i + 1:2}. {c['kind']:6} layer {c['layer']}  x {c['cx']:.3f}  baseline {c['baseline']:.3f}  {c['mode']:5}  score {c['score']}")


def cmd_status(args):
    cur = store.read_json(paths.current(), None)
    if cur is None:
        raise SystemExit("depth-clock: nothing yet, run depth-clock sync")
    print(json.dumps(cur, indent=1)) if args.json else describe(cur)


def _base(an: dict) -> dict:
    p = store.resolve(an)
    p.pop("source", None)
    return p


def cmd_cycle(args):
    an = loaded(args)
    p = _base(an)
    n = len(an["candidates"])
    i = p.get("candidate")
    step = 1 if args.cmd == "next" else -1
    i = (i + step) % n if i is not None else (0 if step > 0 else n - 1)
    c = an["candidates"][i]
    store.save_placement(an["key"], {"layer": c["layer"], "cx": c["cx"], "baseline": c["baseline"],
                                     "size": c["size"], "mode": "auto", "candidate": i})
    publish(an)


def cmd_layer(args):
    an = loaded(args)
    p = _base(an)
    n = len(an["layers"])
    if args.which == "next":
        p["layer"] = (p["layer"] + 1) % n
    elif args.which == "prev":
        p["layer"] = (p["layer"] - 1) % n
    else:
        if not 0 <= int(args.which) < n:
            raise SystemExit(f"depth-clock: layers are 0..{n - 1}")
        p["layer"] = int(args.which)
    p["candidate"] = None
    store.save_placement(an["key"], p)
    publish(an)


def cmd_set(args):
    an = loaded(args)
    p = _base(an)
    for k in ("cx", "baseline", "size", "layer", "mode"):
        v = getattr(args, k)
        if v is not None:
            p[k] = v
    if not 0 <= p["layer"] < len(an["layers"]):
        raise SystemExit(f"depth-clock: layers are 0..{len(an['layers']) - 1}")
    p["size"] = min(max(p["size"], 0.05), 0.8)
    p["candidate"] = None
    store.save_placement(an["key"], p)
    if args.done:
        store.set_editing(False)
    publish(an, args.quiet)


def cmd_reset(args):
    an = loaded(args)
    store.save_placement(an["key"], None)
    publish(an)


def cmd_edit(args):
    on = {"on": True, "off": False}.get(args.state, not store.editing())
    store.set_editing(on)
    cur = store.read_json(paths.current(), None)
    if cur is not None:
        cur["editing"] = on
        store.atomic_write(paths.current(), json.dumps(cur, indent=1))
    print("editing" if on else "done")


def cmd_wallpaper(args):
    print(current_wallpaper(args.wallpaper))


def cmd_preview(args):
    from depth_clock import preview

    an = loaded(args)
    w, h = (int(v) for v in args.size.lower().split("x"))
    preview.render(an, store.resolve(an), args.text, (w, h)).save(args.output)
    print(args.output)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="depth-clock", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help, wallpaper=True):
        p = sub.add_parser(name, help=help, description=help)
        if wallpaper:
            p.add_argument("--wallpaper", help="image to use instead of the current wallpaper")
        p.set_defaults(fn=fn)
        return p

    p = add("sync", cmd_sync, "analyze the wallpaper if needed and update what the clock draws")
    p.add_argument("-q", "--quiet", action="store_true")
    p = add("analyze", cmd_analyze, "analyze a wallpaper and list the places found")
    p.add_argument("--force", action="store_true", help="analyze again even if cached")
    p.add_argument("--json", action="store_true")
    p = add("status", cmd_status, "show what the clock draws now", wallpaper=False)
    p.add_argument("--json", action="store_true")
    add("next", cmd_cycle, "move the clock to the next good place")
    add("prev", cmd_cycle, "move the clock to the previous good place")
    p = add("layer", cmd_layer, "choose what stands in front: next, prev, or a number (0 is nothing)")
    p.add_argument("which")
    p = add("set", cmd_set, "place the clock by hand")
    p.add_argument("--cx", type=float, help="center of the text, fraction of the width")
    p.add_argument("--baseline", type=float, help="baseline, fraction of the height")
    p.add_argument("--size", type=float, help="font size, fraction of the height")
    p.add_argument("--layer", type=int)
    p.add_argument("--mode", choices=["auto", "dark", "light"])
    p.add_argument("--done", action="store_true", help="also leave edit mode")
    p.add_argument("-q", "--quiet", action="store_true")
    add("reset", cmd_reset, "forget the hand placement and use the best place found")
    p = add("edit", cmd_edit, "drag the clock with the mouse: on, off or toggle", wallpaper=False)
    p.add_argument("state", nargs="?", default="toggle", choices=["on", "off", "toggle"])
    add("wallpaper", cmd_wallpaper, "print the wallpaper depth-clock follows")
    p = add("preview", cmd_preview, "render the clock on the wallpaper into an image")
    p.add_argument("-o", "--output", default="depth-clock-preview.png")
    p.add_argument("--text", default="14:25")
    p.add_argument("--size", default="1920x1080", help="image size, WxH")

    args = ap.parse_args(argv)
    args.fn(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
