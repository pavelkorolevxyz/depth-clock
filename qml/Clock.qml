import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

// depth-clock: a clock set behind the foreground of the wallpaper, on every
// screen. The depth-clock CLI does the thinking (what stands in front,
// where the clock goes, its color) and writes current.json; this file draws it.
//
// It sits on the bottom layer, under windows, and takes input only over the
// digits: a double click there, or `depth-clock edit`, opens the editor.
Item {
  id: root

  // Set by shells that load this file as a plugin.
  property var shell: null
  property var manifest: null

  readonly property string home: Quickshell.env("HOME")
  // The CLI ships next to this file, so it works without being on PATH.
  readonly property string cli: Quickshell.env("DEPTH_CLOCK_CLI")
    || decodeURIComponent(Qt.resolvedUrl("../bin/depth-clock").toString().replace(/^file:\/\//, ""))
  readonly property string stateDir: (Quickshell.env("XDG_STATE_HOME") || home + "/.local/state") + "/depth-clock"

  property string wallpaper: ""
  property var cur: null
  property string time: ""

  // What the scenes draw: the saved placement, or the editor's draft.
  property var draft: null
  readonly property var view: (editing && draft) ? draft : place(cur)
  readonly property bool usable: !!cur && cur.ready === true && cur.wallpaper === wallpaper
  readonly property bool editing: usable && cur.editing === true

  function place(c) {
    if (!c || !c.ready) return null
    return { cx: c.cx, baseline: c.baseline, size: c.size, layer: c.layer, mode: c.mode, modeSetting: c.modeSetting }
  }

  function layerOf(v) {
    if (!usable || !v || !cur.layers || v.layer < 0 || v.layer >= cur.layers.length) return null
    return cur.layers[v.layer]
  }

  function maskFor(v) { var l = layerOf(v); return l ? l.mask : "" }
  function tintFor(v) { var l = layerOf(v); return l ? (v.mode === "light" ? l.light : l.dark) : "" }

  onEditingChanged: draft = editing ? place(cur) : null

  function tick() {
    root.time = Qt.formatDateTime(new Date(), "HH:mm")
    var now = new Date()
    clock.interval = Math.max(250, (60 - now.getSeconds()) * 1000 - now.getMilliseconds() + 20)
    clock.restart()
  }

  Component.onCompleted: { tick(); wallpaperProc.running = true }

  Timer { id: clock; repeat: false; onTriggered: root.tick() }

  // The CLI knows where the wallpaper is (see depth-clock wallpaper); ask it
  // now and then, since nothing tells us when the wallpaper changes.
  Process {
    id: wallpaperProc
    command: [root.cli, "wallpaper"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var path = text.trim()
        if (path && path !== root.wallpaper) {
          root.wallpaper = path
          syncProc.running = true
        }
      }
    }
  }

  Timer {
    interval: 30 * 1000
    running: true
    repeat: true
    onTriggered: if (!wallpaperProc.running) wallpaperProc.running = true
  }

  // Analysis of a new wallpaper takes a while the first time; the clock stays
  // hidden until current.json names this wallpaper.
  Process {
    id: syncProc
    command: [root.cli, "sync", "-q", "--wallpaper", root.wallpaper]
    stderr: StdioCollector { onStreamFinished: if (text.trim()) console.warn("depth-clock:", text.trim()) }
  }

  FileView {
    path: root.stateDir + "/current.json"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: {
      try { root.cur = JSON.parse(text()) } catch (e) { root.cur = null }
      // Commands run from the editor (next place, reset) move the draft too.
      if (root.editing) root.draft = root.place(root.cur)
    }
  }

  Variants {
    model: Quickshell.screens

    PanelWindow {
      required property var modelData
      screen: modelData

      anchors { top: true; bottom: true; left: true; right: true }
      exclusionMode: ExclusionMode.Ignore
      color: "transparent"
      // Input only over the digits: a double click there opens the editor,
      // everywhere else clicks go to the desktop as before.
      mask: Region { item: hit }

      WlrLayershell.namespace: "depth-clock"
      WlrLayershell.layer: WlrLayer.Bottom
      WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

      ClockScene {
        id: scene
        anchors.fill: parent
        visible: root.usable && !!root.view
        dpr: screen ? screen.devicePixelRatio : 1
        wallpaper: root.usable ? root.wallpaper : ""
        maskSource: root.maskFor(root.view)
        tintSource: root.tintFor(root.view)
        text: root.time
        fontFamily: root.usable ? root.cur.font : "serif"
        cx: root.view ? root.view.cx : 0.5
        baselineY: root.view ? root.view.baseline : 0.5
        textSize: root.view ? root.view.size : 0.3
      }

      Item {
        id: hit
        readonly property bool active: root.usable && !!root.view && !root.editing && scene.opacity > 0
        x: scene.digitsItem.x
        y: scene.baselineY * scene.height - scene.digitHeight
        width: active ? scene.digitsItem.width : 0
        height: active ? scene.digitHeight : 0
        MouseArea {
          anchors.fill: parent
          onDoubleClicked: editProc.running = true
        }
      }
    }
  }

  Process {
    id: editProc
    command: [root.cli, "edit", "on"]
  }

  Loader {
    active: root.editing
    sourceComponent: Editor { clock: root }
  }
}
