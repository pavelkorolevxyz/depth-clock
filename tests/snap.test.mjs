// node --test tests/
import { test } from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"

// snap.js is a QML JavaScript library: drop the pragma and load its functions.
const src = readFileSync(new URL("../qml/snap.js", import.meta.url), "utf8").replace(".pragma library", "")
const Snap = new Function(`${src}; return { xTargets, yTargets, ridgeUnder, snap }`)()

const W = 1920, H = 1080
const flatRidge = Array(240).fill(0.55)
const ctx = { W, H, width: 600, colonOffset: 10, digitHeight: 240, ridge: flatRidge, peaks: [{ x: 0.7, y: 0.3 }] }

test("free position stays where it is", () => {
  const r = Snap.snap(700, 200, ctx, 8)
  assert.equal(r.cx, 700)
  assert.equal(r.baseline, 200)
  assert.equal(r.gx, null)
  assert.equal(r.gy, null)
})

test("centers the digits themselves, not the text box", () => {
  const ink = { ...ctx, inkDx: 6 }
  const r = Snap.snap(W / 2 - 6 + 5, 200, ink, 8)
  assert.equal(r.cx, W / 2 - 6)
  assert.equal(r.gx.line, W / 2)
  assert.equal(r.gx.label, "center")
  // Vertically the middle of the digits sits on the line: baseline half a digit below.
  const y = Snap.snap(700, H / 2 + 120 + 3, { ...ctx, ridge: [] }, 8)
  assert.equal(y.baseline, H / 2 + 120)
  assert.equal(y.gy.line, H / 2)
})

test("puts the colon over a peak", () => {
  const r = Snap.snap(0.7 * W - 10 + 3, 200, ctx, 8)
  assert.equal(r.cx, 0.7 * W - 10)
  assert.equal(r.gx.line, 0.7 * W)
  assert.equal(r.gx.label, "colon over peak")
})

test("stands on the ridge or sinks a third behind it", () => {
  assert.equal(Snap.snap(700, 0.55 * H + 4, ctx, 8).gy.label, "on the ridge")
  const r = Snap.snap(700, 0.55 * H + 80 - 6, ctx, 8)
  assert.equal(r.baseline, 0.55 * H + 80)
  assert.equal(r.gy.label, "a third behind the ridge")
})

test("no ridge lines over open sky", () => {
  const sky = { ...ctx, ridge: Array(240).fill(1) }
  assert.equal(Snap.ridgeUnder(sky.ridge, W, H, 100, 700), -1)
  assert.ok(!Snap.yTargets(sky, 400).some((t) => t.label.includes("ridge")))
})

test("ridge median follows the clock's span", () => {
  const ridge = Array.from({ length: 240 }, (_, i) => (i < 120 ? 0.4 : 0.6))
  assert.equal(Snap.ridgeUnder(ridge, W, H, 0, 600), 0.4 * H)
  assert.equal(Snap.ridgeUnder(ridge, W, H, 1300, 1900), 0.6 * H)
})

test("the nearest target wins", () => {
  const tight = { ...ctx, peaks: [{ x: (W / 2 + 6 + 10) / W, y: 0.3 }] }
  assert.equal(Snap.snap(W / 2 + 5, 200, tight, 8).gx.label, "colon over peak")
})

test("digits snap to the screen edges and to a margin from them", () => {
  const e = { ...ctx, inkDx: 0, inkWidth: 600, ridge: [], peaks: [] }
  const m = Math.round(H * 0.03)
  // Left edge flush, then at the margin.
  assert.equal(Snap.snap(300 + 4, 200, e, 8).cx, 300)
  assert.equal(Snap.snap(300 + m - 3, 200, e, 8).cx, 300 + m)
  // Right edge at the margin.
  const r = Snap.snap(W - m - 300 + 2, 200, e, 8)
  assert.equal(r.cx, W - m - 300)
  assert.equal(r.gx.line, W - m)
  // Top of the digits at the margin, bottom flush with the screen.
  assert.equal(Snap.snap(700, m + 240 + 5, e, 8).baseline, m + 240)
  assert.equal(Snap.snap(700, H - 6, e, 8).baseline, H)
})

test("dragging a corner scales the clock around the opposite corner", () => {
  const R = new Function(`${src}; return resizeFromCorner`)()
  // A box 600 wide and 240 tall, ink centered on the text, at the screen center.
  const s = { cx: 0.5, baseline: 0.5, size: 0.3, inkDx: 0, inkWidth: 600, digitHeight: 240 }
  const left = W / 2 - 300, right = W / 2 + 300, bottom = H / 2, top = H / 2 - 240
  // Bottom-right pulled to twice the diagonal: double size, top-left fixed.
  const r = R(s, "br", left + 1200, top + 480, W, H, 0.05, 0.9)
  assert.ok(Math.abs(r.size - 0.6) < 1e-9)
  assert.ok(Math.abs(r.cx * W - 600 - left) < 1e-6)          // new left edge
  assert.ok(Math.abs(r.baseline * H - 480 - top) < 1e-6)     // new top edge
  // Top-left pulled to the middle: half size, bottom-right fixed.
  const q = R(s, "tl", (left + right) / 2, (top + bottom) / 2, W, H, 0.05, 0.9)
  assert.ok(Math.abs(q.size - 0.15) < 1e-9)
  assert.ok(Math.abs(q.cx * W + 150 - right) < 1e-6)
  assert.ok(Math.abs(q.baseline * H - bottom) < 1e-6)
  // Limits hold.
  assert.equal(R(s, "br", left, top, W, H, 0.08, 0.6).size, 0.08)
})
