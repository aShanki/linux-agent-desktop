"""Dedicated test UI. Never loads user files, URLs, clipboard, or profiles."""
import argparse
import json
from pathlib import Path


def qt_demo(path):
    from PyQt6 import QtCore, QtGui, QtWidgets
    app = QtWidgets.QApplication([])
    app.setApplicationName('lad-demo')
    window = QtWidgets.QWidget()
    window.setWindowTitle('LAD dedicated test window')
    window.setGeometry(60, 60, 640, 440)
    layout = QtWidgets.QVBoxLayout(window)
    title = QtWidgets.QLabel('Linux Agent Desktop — isolated fixture')
    title.setStyleSheet('background:#2455aa;color:white;padding:20px')
    layout.addWidget(title)
    entry = QtWidgets.QLineEdit()
    entry.setAccessibleName('Message')
    entry.setObjectName('message')
    layout.addWidget(entry)
    button = QtWidgets.QPushButton('Increment')
    button.setAccessibleName('Increment')
    layout.addWidget(button)
    combo = QtWidgets.QComboBox()
    combo.setAccessibleName('Choice')
    combo.addItems(['Alpha', 'Beta', 'Gamma'])
    layout.addWidget(combo)
    scroll = QtWidgets.QScrollArea()
    scroll.setWidgetResizable(True)
    text = QtWidgets.QLabel('\n'.join(f'Line {n}' for n in range(100)))
    scroll.setWidget(text)
    layout.addWidget(scroll)
    dialog_button = QtWidgets.QPushButton('Open dialog')
    layout.addWidget(dialog_button)
    state = {'clicks': 0}
    dialogs = []
    def clicked():
        state['clicks'] += 1
    button.clicked.connect(clicked)
    def dialog():
        box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Icon.Information, 'Test dialog', 'Fixture only',
                                    QtWidgets.QMessageBox.StandardButton.Ok, window)
        dialogs.append(box)
        box.finished.connect(lambda _: dialogs.remove(box))
        box.open()
    dialog_button.clicked.connect(dialog)
    def rect(widget):
        p = widget.mapTo(window, QtCore.QPoint(0, 0))
        return [p.x(), p.y(), widget.width(), widget.height()]
    def save():
        value = dict(state, text=entry.text(), choice=combo.currentText(), scroll=scroll.verticalScrollBar().value(),
                     selection=entry.selectedText(), dialogs=len(dialogs), pid=__import__('os').getpid(),
                     xid=int(window.winId()), width=window.width(), height=window.height(),
                     controls={k: rect(v) for k, v in [('entry', entry), ('button', button), ('combo', combo),
                                                       ('scroll', scroll), ('dialog', dialog_button)]})
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(value))
        tmp.replace(path)
    timer = QtCore.QTimer()
    timer.timeout.connect(save)
    timer.start(30)
    window.show()
    app.exec()


def gtk_demo(path):
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, GLib, Atk
    window = Gtk.Window(title='LAD accessible test window')
    window.set_default_size(640, 440)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    window.add(box)
    entry = Gtk.Entry()
    entry.get_accessible().set_name('Message')
    button = Gtk.Button(label='Increment')
    button.get_accessible().set_name('Increment')
    state = {'clicks': 0}
    def clicked(_):
        state['clicks'] += 1
    button.connect('clicked', clicked)
    box.pack_start(Gtk.Label(label='AT-SPI dedicated fixture'), False, False, 0)
    box.pack_start(entry, False, False, 0)
    box.pack_start(button, False, False, 0)
    def save():
        value = dict(state, text=entry.get_text(), pid=__import__('os').getpid(), xid=getattr(window.get_window(),'get_xid',lambda:0)(),
                     controls={name:list(widget.translate_coordinates(window,0,0))+[widget.get_allocated_width(),widget.get_allocated_height()] for name,widget in [('entry',entry),('button',button)]})
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(value))
        tmp.replace(path)
        return True
    window.connect('destroy', Gtk.main_quit)
    window.show_all()
    GLib.timeout_add(30, save)
    Gtk.main()


def canvas_demo(path):
    """Custom-painted application with no semantic controls to target."""
    from PyQt6 import QtCore, QtGui, QtWidgets
    app=QtWidgets.QApplication([])
    class Canvas(QtWidgets.QWidget):
        def __init__(self):
            super().__init__();self.setWindowTitle('LAD custom canvas fixture');self.resize(640,440)
            self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
            self.points=[];self.clicks=0;self.text='';self.scroll=0
        def mousePressEvent(self,e):
            self.clicks+=1;self.points.append([e.position().x(),e.position().y()]);self.update()
        def mouseMoveEvent(self,e):
            if e.buttons() & QtCore.Qt.MouseButton.LeftButton:
                self.points.append([e.position().x(),e.position().y()]);self.update()
        def keyPressEvent(self,e):self.text+=e.text();self.update()
        def wheelEvent(self,e):self.scroll+=e.angleDelta().y();self.update()
        def paintEvent(self,e):
            p=QtGui.QPainter(self);p.fillRect(self.rect(),QtGui.QColor('white'))
            p.fillRect(0,0,self.width(),60,QtGui.QColor('#2455aa'))
            p.setPen(QtGui.QColor('white'));p.drawText(20,35,'Custom canvas: coordinate input only')
            p.setPen(QtGui.QPen(QtGui.QColor('#dc284f'),3))
            for a,b in zip(self.points,self.points[1:]):p.drawLine(QtCore.QPointF(*a),QtCore.QPointF(*b))
            p.setPen(QtGui.QColor('black'));p.drawText(20,410,self.text)
    window=Canvas();window.show()
    def save():
        value={'pid':__import__('os').getpid(),'clicks':window.clicks,'points':window.points,'text':window.text,'scroll':window.scroll}
        tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value));tmp.replace(path)
    timer=QtCore.QTimer();timer.timeout.connect(save);timer.start(30)
    app.exec()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('kind', choices=['qt', 'gtk', 'canvas'])
    parser.add_argument('state')
    args = parser.parse_args()
    {'qt':qt_demo,'gtk':gtk_demo,'canvas':canvas_demo}[args.kind](Path(args.state))
