.pragma library

// Snapping for the clock editor. Pure functions, so they run in node tests too.
//
// The clock snaps by its text center (x) and its baseline (y), all in pixels.
// Lines it snaps to:
//   x  the digits centered on the screen or a third; their edge at the screen
//      edge or a small margin from it; the colon over a peak
//   y  the same center, thirds and edges; standing on the ridge; the ridge covering a
//      third of the digits (the ridge is measured under the clock's own span)

// Center and thirds line up the middle of the digits themselves, not the text
// box: inkDx is the ink's center minus the text's center, and the digits'
// middle is half a digit above the baseline.

// Vertical targets. ctx: { W, H, width, inkDx, inkWidth, colonOffset, peaks: [{x, y}] }
// colonOffset is the colon's center minus the text's center, in pixels.
function xTargets(ctx) {
  var dx = ctx.inkDx || 0
  var t = [
    { v: ctx.W / 2 - dx, line: ctx.W / 2, label: "center" },
    { v: ctx.W / 3 - dx, line: ctx.W / 3, label: "third" },
    { v: ctx.W * 2 / 3 - dx, line: ctx.W * 2 / 3, label: "third" },
  ]
  // The digits' left or right edge at the screen edge, or a margin in from it.
  var half = (ctx.inkWidth || ctx.width) / 2
  var m = margin(ctx)
  var edges = [0, m, ctx.W - m, ctx.W]
  for (var e = 0; e < edges.length; e++) {
    var left = edges[e] < ctx.W / 2
    t.push({ v: edges[e] + (left ? half : -half) - dx, line: edges[e], label: "edge" })
  }
  var peaks = ctx.peaks || []
  for (var i = 0; i < peaks.length; i++) {
    var px = peaks[i].x * ctx.W
    t.push({ v: px - ctx.colonOffset, line: px, label: "colon over peak" })
  }
  return t
}

// The ridge's median height, in pixels, under the columns from x0 to x1.
// ridge: tops of the layer as fractions of the height, sampled evenly over the width.
function ridgeUnder(ridge, W, H, x0, x1) {
  if (!ridge || ridge.length === 0) return -1
  var n = ridge.length
  var a = Math.max(0, Math.floor(x0 / W * (n - 1)))
  var b = Math.min(n - 1, Math.ceil(x1 / W * (n - 1)))
  var v = []
  for (var i = a; i <= b; i++) if (ridge[i] < 0.999) v.push(ridge[i])
  if (v.length < (b - a + 1) / 2) return -1  // mostly open sky under the clock
  v.sort(function (p, q) { return p - q })
  return v[Math.floor(v.length / 2)] * H
}

// Horizontal targets for a clock centered at cx. ctx adds { digitHeight, ridge }.
function yTargets(ctx, cx) {
  var half = ctx.digitHeight / 2
  var t = [
    { v: ctx.H / 2 + half, line: ctx.H / 2, label: "center" },
    { v: ctx.H / 3 + half, line: ctx.H / 3, label: "third" },
    { v: ctx.H * 2 / 3 + half, line: ctx.H * 2 / 3, label: "third" },
  ]
  // The digits' top or bottom at the screen edge, or a margin in from it.
  var m = margin(ctx)
  t.push({ v: ctx.digitHeight, line: 0, label: "edge" })
  t.push({ v: m + ctx.digitHeight, line: m, label: "edge" })
  t.push({ v: ctx.H - m, line: ctx.H - m, label: "edge" })
  t.push({ v: ctx.H, line: ctx.H - 1, label: "edge" })
  var r = ridgeUnder(ctx.ridge, ctx.W, ctx.H, cx - ctx.width / 2, cx + ctx.width / 2)
  if (r >= 0) {
    t.push({ v: r, line: r, label: "on the ridge" })
    t.push({ v: r + ctx.digitHeight / 3, line: r, label: "a third behind the ridge" })
  }
  return t
}

// A small gap from the screen edges, the same on all sides.
function margin(ctx) {
  return Math.round(Math.min(ctx.W, ctx.H) * 0.03)
}

function nearest(value, targets, threshold) {
  var best = null
  for (var i = 0; i < targets.length; i++) {
    var d = Math.abs(targets[i].v - value)
    if (d <= threshold && (best === null || d < Math.abs(best.v - value))) best = targets[i]
  }
  return best
}

// Snap a raw position. Returns { cx, baseline, gx, gy }: gx and gy are the
// targets snapped to (null when free), for drawing guide lines.
function snap(cx, baseline, ctx, threshold) {
  var gx = nearest(cx, xTargets(ctx), threshold)
  var x = gx ? gx.v : cx
  var gy = nearest(baseline, yTargets(ctx, x), threshold)
  return { cx: x, baseline: gy ? gy.v : baseline, gx: gx, gy: gy }
}

// Resize by dragging a corner of the digits' box; the opposite corner stays.
// s: the start { cx, baseline, size } with the box at that size in pixels
// { inkDx, inkWidth, digitHeight }; corner: "tl", "tr", "bl" or "br";
// (px, py): the pointer. Returns { cx, baseline, size } in fractions.
function resizeFromCorner(s, corner, px, py, W, H, minSize, maxSize) {
  var left = s.cx * W + s.inkDx - s.inkWidth / 2
  var right = left + s.inkWidth
  var bottom = s.baseline * H
  var top = bottom - s.digitHeight
  var fromLeft = corner.charAt(1) === "l", fromTop = corner.charAt(0) === "t"
  var ax = fromLeft ? right : left, ay = fromTop ? bottom : top   // the corner that stays
  var vx = (fromLeft ? left : right) - ax, vy = (fromTop ? top : bottom) - ay
  // How far along the box's diagonal the pointer is: 1 is where the corner was.
  var k = ((px - ax) * vx + (py - ay) * vy) / (vx * vx + vy * vy)
  var size = Math.min(maxSize, Math.max(minSize, s.size * k))
  k = size / s.size
  var w = s.inkWidth * k, dx = s.inkDx * k, h = s.digitHeight * k
  return {
    size: size,
    cx: (fromLeft ? ax - dx - w / 2 : ax - dx + w / 2) / W,
    baseline: (fromTop ? ay : ay + h) / H,
  }
}
