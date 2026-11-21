import QtQuick
import Qt5Compat.GraphicalEffects as GE
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io
import Quickshell.Wayland
import "snap.js" as Snap

// The editor: the whole desktop on top of the windows, with the clock to drag.
// Drag moves it and snaps to the main lines, Shift drags freely, the wheel
// resizes. Enter saves through the CLI, Esc leaves it as it was.
PanelWindow {
  id: editor

  required property var clock   // the clock root: cur, draft, time, helpers

  screen: {
    var m = Hyprland.focusedMonitor
    var name = m ? String(m.name || "") : ""
    for (var i = 0; i < Quickshell.screens.length; i++)
      if (Quickshell.screens[i].name === name) return Quickshell.screens[i]
    return Quickshell.screens.length ? Quickshell.screens[0] : null
  }

  anchors { top: true; bottom: true; left: true; right: true }
  exclusionMode: ExclusionMode.Ignore
  color: "black"

  WlrLayershell.namespace: "depth-clock-editor"
  WlrLayershell.layer: WlrLayer.Overlay
  WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive

  readonly property var d: clock.draft
  readonly property real snapDistance: 10
  property var guideX: null
  property var guideY: null
  property bool dragging: false
  property bool showMask: false   // M: tint what stands in front

  function update(changes) {
    var n = {}
    for (var k in d) n[k] = d[k]
    for (var c in changes) n[c] = changes[c]
    clock.draft = n
  }

  function snapContext() {
    var l = clock.layerOf(d)
    return {
      W: scene.width, H: scene.height,
      width: scene.digitsItem.width,
      inkDx: scene.inkDx,
      inkWidth: scene.inkWidth,
      colonOffset: scene.colonOffset,
      digitHeight: scene.digitHeight,
      ridge: l ? l.ridge : [], peaks: l ? l.peaks : [],
    }
  }

  function moveTo(px, py, free) {
    var r = free ? { cx: px, baseline: py, gx: null, gy: null } : Snap.snap(px, py, snapContext(), snapDistance)
    guideX = r.gx; guideY = r.gy
    update({ cx: r.cx / scene.width, baseline: r.baseline / scene.height })
  }

  function resize(f) {
    update({ size: Math.min(0.6, Math.max(0.08, d.size * f)) })
  }

  function cycleMode() {
    var next = { auto: "dark", dark: "light", light: "auto" }[d.modeSetting || "auto"]
    // In auto, keep the color the CLI picked; it decides again on save.
    update({ modeSetting: next, mode: next === "auto" ? clock.cur.mode : next })
  }

  function save() {
    run([clock.cli, "set", "-q", "--done",
         "--cx", d.cx.toFixed(4), "--baseline", d.baseline.toFixed(4), "--size", d.size.toFixed(4),
         "--layer", String(d.layer), "--mode", d.modeSetting || "auto"])
  }

  function run(cmd) { proc.command = cmd; proc.running = true }

  Process {
    id: proc
    onExited: (code) => { if (code !== 0) console.warn("depth-clock exited with", code) }
    stderr: StdioCollector { onStreamFinished: if (text.trim()) console.warn("depth-clock:", text.trim()) }
  }

  ClockScene {
    id: scene
    anchors.fill: parent
    showWallpaper: true
    fade: false
    dpr: editor.screen ? editor.screen.devicePixelRatio : 1
    wallpaper: clock.wallpaper
    maskSource: clock.maskFor(editor.d)
    tintSource: clock.tintFor(editor.d)
    text: clock.time
    fontFamily: clock.cur.font
    cx: editor.d ? editor.d.cx : 0.5
    baselineY: editor.d ? editor.d.baseline : 0.5
    textSize: editor.d ? editor.d.size : 0.3
  }

  // Mask view: what stands in front of the clock, tinted.
  Image {
    id: maskView
    anchors.fill: parent
    visible: false
    source: editor.showMask && clock.maskFor(editor.d) ? "file://" + clock.maskFor(editor.d) : ""
    fillMode: Image.PreserveAspectCrop
    sourceSize.width: Math.ceil(width * scene.dpr)
    sourceSize.height: Math.ceil(height * scene.dpr)
    asynchronous: true
  }
  GE.ColorOverlay {
    anchors.fill: parent
    visible: editor.showMask && maskView.status === Image.Ready
    source: maskView
    color: "#ff4f5e"
    opacity: 0.5
  }

  // The digits' box, with a handle on each corner to resize.
  readonly property real pad: 16
  readonly property real inkLeft: scene.cx * scene.width + scene.inkDx - scene.inkWidth / 2
  readonly property real digitsTop: scene.baselineY * scene.height - scene.digitHeight

  Rectangle {
    id: frame
    x: editor.inkLeft - editor.pad; y: editor.digitsTop - editor.pad
    width: scene.inkWidth + 2 * editor.pad; height: scene.digitHeight + 2 * editor.pad
    color: "transparent"
    border.color: Qt.rgba(1, 1, 1, editor.dragging ? 0.35 : 0.18)
    border.width: 1
    radius: 6
  }

  // Guide lines for what the clock snapped to.
  Rectangle {
    visible: editor.guideX !== null
    x: editor.guideX ? Math.min(parent.width - 1, Math.round(editor.guideX.line)) : 0
    width: 1; height: parent.height
    color: "#ffd27f"
  }
  Rectangle {
    visible: editor.guideY !== null
    y: editor.guideY ? Math.min(parent.height - 1, Math.round(editor.guideY.line)) : 0
    height: 1; width: parent.width
    color: "#ffd27f"
  }

  MouseArea {
    anchors.fill: parent
    property real offX: 0
    property real offY: 0
    cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
    onPressed: (m) => {
      offX = m.x - editor.d.cx * scene.width
      offY = m.y - editor.d.baseline * scene.height
      editor.dragging = true
    }
    onPositionChanged: (m) => {
      if (pressed) editor.moveTo(m.x - offX, m.y - offY, m.modifiers & Qt.ShiftModifier)
    }
    onReleased: { editor.dragging = false; editor.guideX = null; editor.guideY = null }
    onWheel: (w) => {
      editor.resize(Math.pow(1.04, w.angleDelta.y / 120))
    }
  }

  // Corner handles: drag to resize around the opposite corner. They sit on the
  // frame, a pad away from the digits, so the pointer is offset by that pad.
  Repeater {
    model: ["tl", "tr", "bl", "br"]
    Rectangle {
      required property string modelData
      readonly property bool isLeft: modelData.charAt(1) === "l"
      readonly property bool isTop: modelData.charAt(0) === "t"
      width: 12; height: 12; radius: 2
      x: (isLeft ? frame.x : frame.x + frame.width) - width / 2
      y: (isTop ? frame.y : frame.y + frame.height) - height / 2
      color: handleArea.pressed || handleArea.containsMouse ? "white" : Qt.rgba(1, 1, 1, 0.7)
      border.color: Qt.rgba(0, 0, 0, 0.5)

      MouseArea {
        id: handleArea
        anchors.fill: parent
        anchors.margins: -6
        hoverEnabled: true
        cursorShape: parent.isLeft === parent.isTop ? Qt.SizeFDiagCursor : Qt.SizeBDiagCursor
        property var start: null
        onPressed: {
          start = { cx: editor.d.cx, baseline: editor.d.baseline, size: editor.d.size,
                    inkDx: scene.inkDx, inkWidth: scene.inkWidth, digitHeight: scene.digitHeight }
          editor.dragging = true
        }
        onPositionChanged: (m) => {
          if (!pressed || !start) return
          var p = mapToItem(scene, m.x, m.y)
          // Where the digits' corner would be, without the frame's pad.
          var px = p.x + (parent.isLeft ? editor.pad : -editor.pad)
          var py = p.y + (parent.isTop ? editor.pad : -editor.pad)
          editor.update(Snap.resizeFromCorner(start, parent.modelData, px, py, scene.width, scene.height, 0.08, 0.6))
        }
        onReleased: { start = null; editor.dragging = false }
      }
    }
  }

  Item {
    anchors.fill: parent
    focus: true
    Keys.onPressed: (e) => {
      var step = (e.modifiers & Qt.ShiftModifier) ? 10 : 1
      if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) editor.save()
      else if (e.key === Qt.Key_Escape) editor.run([clock.cli, "edit", "off"])
      else if (e.key === Qt.Key_Left) editor.update({ cx: editor.d.cx - step / scene.width })
      else if (e.key === Qt.Key_Right) editor.update({ cx: editor.d.cx + step / scene.width })
      else if (e.key === Qt.Key_Up) editor.update({ baseline: editor.d.baseline - step / scene.height })
      else if (e.key === Qt.Key_Down) editor.update({ baseline: editor.d.baseline + step / scene.height })
      else if (e.key === Qt.Key_L) {
        var n = clock.cur.layers.length
        editor.update({ layer: (editor.d.layer + ((e.modifiers & Qt.ShiftModifier) ? n - 1 : 1)) % n })
      }
      else if (e.key === Qt.Key_Plus || e.key === Qt.Key_Equal) editor.resize(1.04)
      else if (e.key === Qt.Key_Minus) editor.resize(1 / 1.04)
      else if (e.key === Qt.Key_D) editor.cycleMode()
      else if (e.key === Qt.Key_M) editor.showMask = !editor.showMask
      else if (e.key === Qt.Key_N) editor.run([clock.cli, (e.modifiers & Qt.ShiftModifier) ? "prev" : "next"])
      else if (e.key === Qt.Key_R) editor.run([clock.cli, "reset"])
      else return
      e.accepted = true
    }
  }

  // What the keys do, and what is in front now.
  Rectangle {
    anchors.horizontalCenter: parent.horizontalCenter
    anchors.bottom: parent.bottom
    anchors.bottomMargin: 28
    width: hint.implicitWidth + 32
    height: hint.implicitHeight + 16
    radius: 8
    color: Qt.rgba(0, 0, 0, 0.6)
    Text {
      id: hint
      anchors.centerIn: parent
      color: "white"
      font.pixelSize: 14
      text: {
        var layers = clock.cur.layers.length - 1
        var l = editor.d ? editor.d.layer : 0
        var front = l === 0 ? "nothing in front" : "layer " + l + " of " + layers
        var color = editor.d ? (editor.d.modeSetting || "auto") : "auto"
        return "drag to move, Shift for no snapping · corners, wheel or +/−: size · L: " + front + " · M: mask " + (editor.showMask ? "on" : "off") + " · D: color " + color
          + " · N: next place · R: auto · Enter: save · Esc: cancel"
      }
    }
  }
}
