"""Observe one explicitly selected live KWin window's client geometry only."""
import json
import threading
import uuid
from pathlib import Path
import gi

gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib


class WindowTracker:
    def __init__(self, window_id, directory):
        self.geometry = None
        self.closed = False
        self.window_id = window_id
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        suffix = 'i' + uuid.uuid4().hex
        self.name = 'org.lad.Tracker.' + suffix
        self.owner = Gio.bus_own_name_on_connection(self.bus, self.name, Gio.BusNameOwnerFlags.NONE, None, None)
        xml = '<node><interface name="org.lad.Tracker"><method name="Update"><arg type="s" direction="in"/></method></interface></node>'
        interface = Gio.DBusNodeInfo.new_for_xml(xml).interfaces[0]
        self.registration = self.bus.register_object('/Tracker', interface, self.update, None, None)
        self.loop = GLib.MainLoop()
        threading.Thread(target=self.loop.run, daemon=True).start()
        self.label = 'lad-track-' + suffix
        self.path = Path(directory).resolve() / (self.label + '.js')
        script = '''var id=ID;var t=null;var ws=workspace.stackingOrder;
for(var i=0;i<ws.length;i++){if(ws[i].internalId.toString()===id)t=ws[i];}
function publish(){if(!t)return;var r=t.clientGeometry;
callDBus(NAME,"/Tracker","org.lad.Tracker","Update",JSON.stringify({id:id,pid:t.pid,x:r.x,y:r.y,width:r.width,height:r.height,minimized:t.minimized,active:t.active}));}
if(t){t.frameGeometryChanged.connect(publish);t.minimizedChanged.connect(publish);publish();}'''
        self.path.write_text(script.replace('ID', json.dumps(window_id)).replace('NAME', json.dumps(self.name)))
        ident = self.call('/Scripting', 'org.kde.kwin.Scripting', 'loadScript',
                          GLib.Variant('(ss)', (str(self.path), self.label)))
        self.call('/Scripting/Script' + str(ident), 'org.kde.kwin.Script', 'run')

    def call(self, path, interface, method, args=None):
        reply = self.bus.call_sync('org.kde.KWin', path, interface, method, args, None,
                                   Gio.DBusCallFlags.NONE, 1000, None).unpack()
        return reply[0] if reply else None

    def update(self, conn, sender, path, interface, method, args, invocation):
        value = json.loads(args.unpack()[0])
        if value.get('id') == self.window_id:
            self.geometry = value
        invocation.return_value(GLib.Variant('()', ()))

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.call('/Scripting', 'org.kde.kwin.Scripting', 'unloadScript', GLib.Variant('(s)', (self.label,)))
        finally:
            self.path.unlink(missing_ok=True)
            self.bus.unregister_object(self.registration)
            Gio.bus_unown_name(self.owner)
            self.loop.quit()
