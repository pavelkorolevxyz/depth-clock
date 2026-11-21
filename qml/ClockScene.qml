import QtQuick
import Qt5Compat.GraphicalEffects as GE

// The clock over one screen: digits colored by a tint image, then the
// wallpaper again on top of them, cut by the mask of what stands in front.
// Every position is a fraction of the screen, so one placement fits all screens.
Item {
  id: scene

  property string wallpaper: ""
  property string maskSource: ""   // empty: nothing in front
  property string tintSource: ""
  property string text: ""
  property string fontFamily: "serif"
  property real cx: 0.5            // text center, of the width
  property real baselineY: 0.5     // the text baseline, of the height
  property real textSize: 0.3      // font pixel size, of the height
  property real dpr: 1
  property bool showWallpaper: false  // the editor draws the whole desktop
  property bool fade: true

  // Geometry the editor snaps with.
  readonly property alias digitsItem: digits
  // FontMetrics methods are not bindings: read the size so these update with it.
  readonly property real digitHeight: { metrics.font.pixelSize; return metrics.tightBoundingRect("0").height }
  readonly property real inkDx: {
    metrics.font.pixelSize
    var r = metrics.tightBoundingRect(text)
    return r.x + r.width / 2 - digits.width / 2
  }
  readonly property real inkWidth: { metrics.font.pixelSize; return metrics.tightBoundingRect(text).width }
  readonly property real colonOffset: {
    metrics.font.pixelSize
    return metrics.advanceWidth(text.slice(0, 2)) + metrics.advanceWidth(":") / 2 - digits.width / 2
  }

  readonly property bool ready: wallpaper !== "" && tintSource !== ""
    && wallImage.status === Image.Ready && tintImage.status === Image.Ready
    && (maskSource === "" || maskImage.status === Image.Ready)

  // Hide at once when something reloads, fade in once all of it is ready, so the
  // digits never show without what stands in front of them.
  opacity: 0
  onReadyChanged: {
    if (!ready) { fadeIn.stop(); opacity = 0 }
    else if (fade) fadeIn.restart()
    else opacity = 1
  }
  Component.onCompleted: if (ready) opacity = 1
  NumberAnimation { id: fadeIn; target: scene; property: "opacity"; to: 1; duration: 900; easing.type: Easing.OutCubic }

  Image {
    anchors.fill: parent
    visible: scene.showWallpaper
    source: wallImage.source
    fillMode: Image.PreserveAspectCrop
    sourceSize: wallImage.sourceSize
    asynchronous: true
  }

  FontMetrics {
    id: metrics
    font.family: scene.fontFamily
    font.pixelSize: Math.max(8, Math.round(scene.textSize * scene.height))
  }

  // White digits, used only as the alpha for the tint.
  // CurveRendering draws real outlines; the distance field facets large glyphs.
  Text {
    id: digits
    visible: false
    layer.enabled: true
    layer.textureSize: Qt.size(width * scene.dpr, height * scene.dpr)
    layer.smooth: true
    renderType: Text.CurveRendering
    text: scene.text
    color: "white"
    font: metrics.font
    x: scene.cx * scene.width - width / 2
    y: scene.baselineY * scene.height - baselineOffset
  }

  // The tint image, cut to the digits' box.
  Item {
    id: tintBox
    x: digits.x; y: digits.y; width: digits.width; height: digits.height
    visible: false
    clip: true
    layer.enabled: true
    layer.textureSize: Qt.size(width * scene.dpr, height * scene.dpr)
    Image {
      id: tintImage
      x: -tintBox.x; y: -tintBox.y
      width: scene.width; height: scene.height
      source: scene.tintSource ? "file://" + scene.tintSource : ""
      smooth: true
      asynchronous: true
    }
  }

  GE.OpacityMask {
    x: digits.x; y: digits.y; width: digits.width; height: digits.height
    source: tintBox
    maskSource: digits
    // Not cached: a cache rebuilt on each minute can show an empty frame.
    cached: false
  }

  // The wallpaper again, only where the mask is opaque.
  Item {
    anchors.fill: parent
    visible: scene.maskSource !== "" && wallImage.status === Image.Ready && maskImage.status === Image.Ready

    Image {
      id: wallImage
      anchors.fill: parent
      visible: false
      source: scene.wallpaper ? "file://" + scene.wallpaper : ""
      fillMode: Image.PreserveAspectCrop
      sourceSize.width: Math.ceil(parent.width * scene.dpr)
      sourceSize.height: Math.ceil(parent.height * scene.dpr)
      asynchronous: true
    }

    Image {
      id: maskImage
      anchors.fill: parent
      visible: false
      layer.enabled: true
      layer.textureSize: Qt.size(width * scene.dpr, height * scene.dpr)
      layer.smooth: true
      source: scene.maskSource ? "file://" + scene.maskSource : ""
      fillMode: Image.PreserveAspectCrop
      sourceSize.width: Math.ceil(parent.width * scene.dpr)
      sourceSize.height: Math.ceil(parent.height * scene.dpr)
      asynchronous: true
    }

    GE.OpacityMask {
      anchors.fill: parent
      source: wallImage
      maskSource: maskImage
      cached: true
    }
  }
}
