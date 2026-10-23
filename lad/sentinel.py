"""Dedicated opaque foreground fixture: records any misrouted input, no user content."""
import json
import sys
from pathlib import Path
from PyQt6 import QtCore,QtWidgets

app=QtWidgets.QApplication([])
path=Path(sys.argv[1])
class Sentinel(QtWidgets.QWidget):
    def __init__(self):
        super().__init__();self.keys=0;self.clicks=0;self.focus_losses=0;self.was_active=False
        self.setWindowTitle('LAD sentinel')
        self.setStyleSheet('background:#de2599')
    def changeEvent(self,event):
        if event.type()==QtCore.QEvent.Type.ActivationChange:
            active=self.isActiveWindow()
            if self.was_active and not active:self.focus_losses+=1
            self.was_active=active
        super().changeEvent(event)
    def keyPressEvent(self,event):self.keys+=1
    def mousePressEvent(self,event):self.clicks+=1
window=Sentinel();window.showMaximized()
def save():
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps({'keys':window.keys,'clicks':window.clicks,'active':window.isActiveWindow(),'focus_losses':window.focus_losses}));tmp.replace(path)
timer=QtCore.QTimer();timer.timeout.connect(save);timer.start(30)
app.exec()
