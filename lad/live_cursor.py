"""Input-transparent agent cursor anchored to one existing KWin window.

This is an indicator, never an input injector. Agent actions must independently
resolve and validate their target. No window titles or screenshots are read.
"""
import argparse
import json
import os
import signal
import time
from pathlib import Path
from PyQt6 import QtCore, QtGui, QtWidgets
import gi

gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib
from .session import process_start
from .window_tracker import WindowTracker
from .cursor_state import project_point, is_active, Motion


class Cursor(QtWidgets.QWidget):
    def __init__(self, window_id, pid, state_path, ready_path=None):
        flags = (QtCore.Qt.WindowType.ToolTip | QtCore.Qt.WindowType.FramelessWindowHint |
                 QtCore.Qt.WindowType.WindowStaysOnTopHint | QtCore.Qt.WindowType.WindowTransparentForInput |
                 QtCore.Qt.WindowType.WindowDoesNotAcceptFocus | QtCore.Qt.WindowType.NoDropShadowWindowHint)
        super().__init__(None, flags)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setWindowOpacity(0.0)
        self.resize(52, 62)
        self.arrow = QtGui.QPolygon([QtCore.QPoint(2, 2), QtCore.QPoint(3, 24),
                                    QtCore.QPoint(9, 18), QtCore.QPoint(15, 29),
                                    QtCore.QPoint(20, 26), QtCore.QPoint(14, 16),
                                    QtCore.QPoint(23, 15)])
        self.arrow.translate(20, 20)
        self.setMask(QtGui.QRegion(self.arrow))
        self.motion = None
        self.motion_space = None
        self.click_seq = 0
        self.clicked_at = -10
        self.window_id, self.pid = window_id, pid
        self.start = process_start(pid)
        self.state_path = Path(state_path)
        self.tracker = WindowTracker(window_id, self.state_path.parent)
        self.position = None
        self.show()
        # KDE's tooltip styling can install a compositor shadow even for a
        # transparent widget. Remove only this overlay's shadow property.
        from Xlib import display
        self.x_display = display.Display()
        self.x_window = self.x_display.create_resource_object('window', int(self.winId()))
        self.shadow_atom = self.x_display.intern_atom('_KDE_NET_WM_SHADOW')
        self.x_window.delete_property(self.shadow_atom)
        self.x_display.flush()
        self.refresh()
        if ready_path:
            Path(ready_path).write_text(json.dumps({'window_id': int(self.winId()), 'pid': os.getpid()}))
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(33)

    def refresh(self):
        if hasattr(self, 'x_window'):
            self.x_window.delete_property(self.shadow_atom)
            self.x_display.flush()
        if not self.start or process_start(self.pid) != self.start:
            self.close()
            return
        try:
            info = self.tracker.geometry
            if not info or info.get('pid') != self.pid or info.get('minimized'):
                self.setWindowOpacity(0.0)
                return
            rect = tuple(info[key] for key in ('x', 'y', 'width', 'height'))
            state = json.loads(self.state_path.read_text())
            now = time.monotonic()
            raw = (state.get('x', 80), state.get('y', 140))
            space = state.get('space', 'window')
            if self.motion is None or self.motion_space != space:
                self.motion = Motion(raw, now)
                self.motion_space = space
            else:
                self.motion.move(raw, now)
            point = project_point(rect, dict(state, x=self.motion.position(now)[0], y=self.motion.position(now)[1]))
            sequence = state.get('click_seq', 0)
            if sequence != self.click_seq:
                self.click_seq = sequence
                self.clicked_at = now
            if point is None:
                self.setWindowOpacity(0.0)
                return
            self.setWindowOpacity(.65 if is_active(state) else 0.0)
            # Track target translations immediately, without smoothing behind it.
            self.position = point
            self.move(round(point[0]) - 22, round(point[1]) - 22)
            self.update()
        except (OSError, ValueError, GLib.Error, TypeError):
            self.setWindowOpacity(0.0)

    def closeEvent(self, event):
        self.tracker.close()
        if hasattr(self, 'x_display'):
            self.x_display.close()
        super().closeEvent(event)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), QtCore.Qt.GlobalColor.transparent)
        painter.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_SourceOver)
        progress = (time.monotonic() - self.clicked_at) / .4
        mask = QtGui.QRegion(self.arrow)
        if 0 <= progress < 1:
            radius = 5 + 16 * progress
            painter.setPen(QtGui.QPen(QtGui.QColor(137, 117, 255, int(210 * (1 - progress))), 2))
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QtCore.QPointF(22, 22), radius, radius)
            mask |= QtGui.QRegion(QtCore.QRect(0, 0, 44, 44), QtGui.QRegion.RegionType.Ellipse)
        self.setMask(mask)
        painter.setPen(QtGui.QPen(QtGui.QColor(40, 35, 60, 190), 1.3))
        painter.setBrush(QtGui.QColor(166, 154, 245, 200))
        painter.drawPolygon(self.arrow)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--window-id', required=True)
    parser.add_argument('--pid', required=True, type=int)
    parser.add_argument('--state', required=True, type=Path)
    parser.add_argument('--ready', type=Path)
    args = parser.parse_args()
    app = QtWidgets.QApplication([])
    widget = Cursor(args.window_id, args.pid, args.state, args.ready)
    def stop(*_):
        widget.close()
        app.quit()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    app.exec()


if __name__ == '__main__':
    main()
