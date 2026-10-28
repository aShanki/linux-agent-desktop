"""Read held input on a frame timer, as games do, rather than counting events."""
import json
import sys
from pathlib import Path
from PyQt6 import QtCore, QtWidgets

app = QtWidgets.QApplication([])
path = Path(sys.argv[1])


class Window(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.resize(400, 200)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.mouse_down = self.key_down = False
        self.last_mouse = self.last_key = False
        self.clicks = self.keys = self.key_ticks = 0

    def mousePressEvent(self, event):
        self.mouse_down = True

    def mouseReleaseEvent(self, event):
        self.mouse_down = False

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key.Key_W:
            self.key_down = True

    def keyReleaseEvent(self, event):
        if event.key() == QtCore.Qt.Key.Key_W and not event.isAutoRepeat():
            self.key_down = False

    def frame(self):
        self.clicks += self.mouse_down and not self.last_mouse
        self.keys += self.key_down and not self.last_key
        self.key_ticks += self.key_down
        self.last_mouse, self.last_key = self.mouse_down, self.key_down
        value = {k: getattr(self, k) for k in ('clicks', 'keys', 'key_ticks', 'mouse_down', 'key_down')}
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(value))
        tmp.replace(path)


window = Window()
timer = QtCore.QTimer()
timer.timeout.connect(window.frame)
timer.start(50)
window.show()
app.exec()
