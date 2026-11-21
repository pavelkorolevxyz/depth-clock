import Quickshell

// Run the clock on its own: qs -p path/to/depth-clock/qml
// Shells with plugins load Clock.qml directly instead (see ../manifest.json).
ShellRoot {
  Clock {}
}
