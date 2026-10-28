"""Native Wayland on an owned virtual compositor, never the user's compositor."""
import base64
import ctypes as C
import json
import os
import select
import time
import uuid
from pathlib import Path
import gi
from .errors import DesktopError, require

gi.require_version('Gio','2.0')
from gi.repository import Gio,GLib

LETTER_KEYS = dict(zip('qwertyuiopasdfghjklzxcvbnm',
                      [16,17,18,19,20,21,22,23,24,25,30,31,32,33,34,35,36,37,38,44,45,46,47,48,49,50]))
KEYS = dict(LETTER_KEYS, Return=28, Tab=15, Escape=1, BackSpace=14,
            Down=108, Up=103, Left=105, Right=106, Home=102, End=107,
            PageUp=104, PageDown=109, Delete=111, space=57)
KEYS.update({f'F{i}': 58+i for i in range(1,11)})
KEYS.update(F11=87, F12=88)


class PrivateBus:
    def __init__(self):
        self.root=Path(os.environ.get('LAD_ISOLATED_ROOT','/nonexistent'))
        require(self.root.is_dir() and (self.root/'runtime').resolve()==Path(os.environ.get('XDG_RUNTIME_DIR','/')).resolve(),
                'unsafe_target','Only a task-owned private KWin runtime is allowed')
        require(os.environ.get('WAYLAND_DISPLAY')=='lad-isolated','unsafe_target','Refusing a host Wayland display')
        self.bus=Gio.bus_get_sync(Gio.BusType.SESSION,None)
        reply=self.bus.call_sync('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus',
                                 'GetConnectionUnixProcessID',GLib.Variant('(s)',('org.kde.KWin',)),
                                 GLib.VariantType.new('(u)'),Gio.DBusCallFlags.NONE,2000,None)
        require(reply.unpack()[0]==int(os.environ['LAD_KWIN_PID']),'unsafe_target','Private compositor identity changed')

    def call(self,path,interface,method,args=None):
        return self.bus.call_sync('org.kde.KWin',path,interface,method,args,None,Gio.DBusCallFlags.NONE,3000,None)


class EmulatedInput:
    def __init__(self,bus):
        self.bus=bus  # KWin revokes EIS when its D-Bus client disconnects.
        result,fds=bus.bus.call_with_unix_fd_list_sync('org.kde.KWin','/org/kde/KWin/EIS/RemoteDesktop',
                 'org.kde.KWin.EIS.RemoteDesktop','connectToEIS',GLib.Variant('(i)',(3,)),None,
                 Gio.DBusCallFlags.NONE,3000,None,None)
        values=result.unpack()
        # Qt returns its function return value first, then out parameters.
        fd=fds.get(values[0])
        self.lib=C.CDLL('libei.so.1')
        ptr=C.c_void_p;integer=C.c_int;u32=C.c_uint32;u64=C.c_uint64;double=C.c_double
        definitions={
            'ei_new_sender':(ptr,[ptr]),'ei_configure_name':(None,[ptr,C.c_char_p]),
            'ei_setup_backend_fd':(integer,[ptr,integer]),'ei_get_fd':(integer,[ptr]),
            'ei_dispatch':(None,[ptr]),'ei_get_event':(ptr,[ptr]),'ei_event_get_type':(integer,[ptr]),
            'ei_event_get_device':(ptr,[ptr]),'ei_event_get_seat':(ptr,[ptr]),'ei_event_unref':(ptr,[ptr]),
            'ei_device_ref':(ptr,[ptr]),'ei_device_unref':(ptr,[ptr]),'ei_unref':(ptr,[ptr]),
            'ei_device_has_capability':(C.c_bool,[ptr,integer]),'ei_device_start_emulating':(None,[ptr,u32]),
            'ei_device_stop_emulating':(None,[ptr]),'ei_device_frame':(None,[ptr,u64]),'ei_now':(u64,[ptr]),
            'ei_device_pointer_motion_absolute':(None,[ptr,double,double]),
            'ei_device_button_button':(None,[ptr,u32,C.c_bool]),'ei_device_scroll_delta':(None,[ptr,double,double]),
            'ei_device_keyboard_key':(None,[ptr,u32,C.c_bool])}
        for name,(returns,args) in definitions.items():
            fn=getattr(self.lib,name);fn.restype=returns;fn.argtypes=args
        self.lib.ei_seat_bind_capabilities.argtypes=[ptr]
        self.lib.ei_seat_bind_capabilities.restype=None
        self.context=self.lib.ei_new_sender(None)
        self.held_keys=set();self.button_down=False;self.closed=False
        self.lib.ei_configure_name(self.context,b'LAD isolated test input')
        require(self.lib.ei_setup_backend_fd(self.context,fd)==0,'input_unavailable','Cannot connect private EIS input')
        self.pointer=None;self.keyboard=None;self.devices=[]
        end=time.monotonic()+3
        while not (self.pointer and self.keyboard):
            require(time.monotonic()<end,'input_unavailable','Private compositor did not offer input devices')
            self.pump(.1)

    def pump(self,wait=0):
        if wait:select.select([self.lib.ei_get_fd(self.context)],[],[],wait)
        self.lib.ei_dispatch(self.context)
        while event:=self.lib.ei_get_event(self.context):
            try:
                kind=self.lib.ei_event_get_type(event)
                if kind==2:raise DesktopError('input_unavailable','Private EIS disconnected')
                if kind==3:
                    seat=self.lib.ei_event_get_seat(event)
                    self.lib.ei_seat_bind_capabilities(seat,C.c_int(2),C.c_int(4),C.c_int(16),C.c_int(32),C.c_void_p())
                if kind==8:
                    device=self.lib.ei_event_get_device(event)
                    if device not in self.devices:
                        self.devices.append(self.lib.ei_device_ref(device))
                        self.lib.ei_device_start_emulating(device,1)
                    if self.lib.ei_device_has_capability(device,2):self.pointer=device
                    if self.lib.ei_device_has_capability(device,4):self.keyboard=device
            finally:self.lib.ei_event_unref(event)

    def frame(self,device):
        self.lib.ei_device_frame(device,self.lib.ei_now(self.context));self.pump()

    def move(self,x,y):
        self.lib.ei_device_pointer_motion_absolute(self.pointer,x,y);self.frame(self.pointer)

    def button(self,pressed):
        self.button_down=pressed
        self.lib.ei_device_button_button(self.pointer,0x110,pressed);self.frame(self.pointer)

    def key(self,key,pressed):
        if pressed:self.held_keys.add(key)
        else:self.held_keys.discard(key)
        self.lib.ei_device_keyboard_key(self.keyboard,key,pressed);self.frame(self.keyboard)

    def wait(self,seconds):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            self.pump(min(.05,max(0,end-time.monotonic())))

    def close(self):
        if self.closed:return
        self.closed=True
        try:
            if self.pointer and self.button_down:self.button(False)
            for key in list(self.held_keys):self.key(key,False)
        finally:
            for d in self.devices:
                self.lib.ei_device_stop_emulating(d);self.lib.ei_device_unref(d)
            self.lib.ei_dispatch(self.context);self.lib.ei_unref(self.context)
            self.bus=None


class KWin(PrivateBus):
    def __init__(self,pid):
        super().__init__();self.pid=pid

    def windows(self):
        nonce=uuid.uuid4().hex
        script=self.root/(nonce+'.js')
        source='''var out=[];var ws=workspace.stackingOrder;
var stacking=[];
for(var i=0;i<ws.length;i++){var w=ws[i];var f=w.frameGeometry;stacking.push({id:w.internalId.toString(),x:f.x,y:f.y,width:f.width,height:f.height,minimized:w.minimized});if(w.pid===PID){var r=w.clientGeometry;out.push({native_id:w.internalId.toString(),pid:w.pid,x:r.x,y:r.y,width:r.width,height:r.height,active:w.active,minimized:w.minimized});}}
var screens=[];for(var i=0;i<workspace.screens.length;i++){var g=workspace.screens[i].geometry;screens.push({x:g.x,y:g.y,width:g.width,height:g.height});}
print("LAD_NONCE:"+JSON.stringify({windows:out,stacking:stacking,screens:screens,pointer:{x:workspace.cursorPos.x,y:workspace.cursorPos.y}}));'''.replace('PID',str(self.pid)).replace('NONCE',nonce)
        script.write_text(source)
        try:
            ident=self.call('/Scripting','org.kde.kwin.Scripting','loadScript',GLib.Variant('(ss)',(str(script),nonce))).unpack()[0]
            self.call('/Scripting/Script'+str(ident),'org.kde.kwin.Script','run')
            end=time.monotonic()+2
            while time.monotonic()<end:
                text=(self.root/'process.log').read_text(errors='replace')
                for line in reversed(text.splitlines()):
                    if 'LAD_'+nonce+':' in line:
                        return json.loads(line.split('LAD_'+nonce+':',1)[1])
                time.sleep(.02)
            raise DesktopError('discovery_failed','Private compositor did not return window metadata')
        finally:
            self.call('/Scripting','org.kde.kwin.Scripting','unloadScript',GLib.Variant('(s)',(nonce,)))
            script.unlink(missing_ok=True)

    def capture(self,window):
        readfd,writefd=os.pipe()
        fdlist=Gio.UnixFDList.new();handle=fdlist.append(writefd)
        options={'include-decoration':GLib.Variant('b',False),'include-shadow':GLib.Variant('b',False),
                 'native-resolution':GLib.Variant('b',True)}
        try:
            result,_=self.bus.call_with_unix_fd_list_sync('org.kde.KWin','/org/kde/KWin/ScreenShot2',
                 'org.kde.KWin.ScreenShot2','CaptureWindow',GLib.Variant('(sa{sv}h)',(window['native_id'],options,handle)),
                 None,Gio.DBusCallFlags.NONE,3000,fdlist,None)
            meta=result.unpack()[0];needed=meta['stride']*meta['height'];data=bytearray()
            end=time.monotonic()+3
            while len(data)<needed:
                require(time.monotonic()<end,'timeout','Private screenshot pipe timed out')
                if select.select([readfd],[],[],.1)[0]:
                    block=os.read(readfd,min(65536,needed-len(data)))
                    require(bool(block),'capture_failed','Private screenshot pipe closed early');data.extend(block)
            from PyQt6 import QtGui,QtCore
            image=QtGui.QImage(bytes(data),meta['width'],meta['height'],meta['stride'],QtGui.QImage.Format(meta['format']))
            output=QtCore.QByteArray();buffer=QtCore.QBuffer(output);buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
            require(image.save(buffer,'PNG'),'capture_failed','Cannot encode compositor frame')
            return {'png':base64.b64encode(bytes(output)).decode(),'width':meta['width'],'height':meta['height'],
                    'scale':meta['scale'],'host_input_isolated':True}
        finally:os.close(readfd);os.close(writefd)

    def execute(self,op):
        scene=self.windows();windows=scene['windows'];action=op['action']
        for w in windows:w['coordinate_space']='window logical pixels'
        if action=='discover':return {'windows':windows,'outputs':scene['screens']}
        matches=[w for w in windows if w['native_id']==op.get('native_id')]
        require(len(matches)==1,'stale_target','The owned native Wayland window is no longer available')
        w=matches[0]
        if action=='geometry':return w
        if action=='screenshot':return self.capture(w)
        if action in ('tree','set_text','invoke'):
            from .accessibility import Accessibility
            return dict(Accessibility(self.pid).execute(op),host_input_isolated=True)
        require(action in ('click','drag','scroll','type','key'),'unsupported_action','Unsupported native Wayland operation')
        if 'hold_ms' in op:
            require(action in ('click','key'),'invalid_argument','hold_ms applies only to click and key')
        hold_ms=op.get('hold_ms',150)
        require(type(hold_ms) is int and 1<=hold_ms<=10000,'invalid_argument','hold_ms must be an integer from 1 to 10000')
        require(not w['minimized'],'not_viewable','Restore the isolated window before coordinate input')
        if action in ('type','key'):
            require(w['active'],'target_not_active','Keyboard input requires the active window inside the private compositor')
        if action in ('click','drag','scroll'):
            x,y=op.get('x'),op.get('y')
            require(type(x) in (int,float) and type(y) in (int,float) and 0<=x<w['width'] and 0<=y<w['height'],
                    'out_of_bounds','Use logical coordinates inside the private window')
            points=[(w['x']+x,w['y']+y)]
            if action=='drag':
                ex,ey=op.get('end_x'),op.get('end_y')
                require(type(ex) in (int,float) and type(ey) in (int,float) and 0<=ex<w['width'] and 0<=ey<w['height'],
                        'out_of_bounds','Drag must end inside the private window')
                points.extend((w['x']+x+(ex-x)*i/10,w['y']+y+(ey-y)*i/10) for i in range(1,11))
            for px,py in points:
                under=[v for v in scene['stacking'] if not v['minimized'] and v['x']<=px<v['x']+v['width'] and v['y']<=py<v['y']+v['height']]
                require(under and under[-1]['id']==w['native_id'],'occluded_target','Another private window covers the input point; use semantic input')
        inputs=EmulatedInput(self)
        try:
            if action in ('click','drag','scroll'):
                x,y=op.get('x'),op.get('y')
                require(type(x) in (int,float) and type(y) in (int,float) and 0<=x<w['width'] and 0<=y<w['height'],
                        'out_of_bounds','Use logical coordinates inside the private window')
                if action=='drag':
                    ex,ey=op.get('end_x'),op.get('end_y')
                    require(type(ex) in (int,float) and type(ey) in (int,float) and 0<=ex<w['width'] and 0<=ey<w['height'],
                            'out_of_bounds','Drag must end inside the private window')
                inputs.move(w['x']+x,w['y']+y);inputs.pump(.06)
                if action=='scroll':
                    steps=op.get('steps',1)
                    require(type(steps) is int and 0<abs(steps)<=20,'invalid_argument','Scroll steps must be within 20')
                    inputs.lib.ei_device_scroll_delta(inputs.pointer,0,steps*80);inputs.frame(inputs.pointer)
                else:
                    inputs.button(True)
                    if action=='drag':
                        for i in range(1,11):inputs.move(w['x']+x+(ex-x)*i/10,w['y']+y+(ey-y)*i/10);inputs.pump(.01)
                    else:inputs.wait(hold_ms/1000)
                    inputs.button(False)
            elif action=='key':
                require(op.get('key') in KEYS,'unsupported_key','Key is outside the private-compositor key subset')
                require(op.get('modifier','none') in ('none','ctrl','shift','alt'),'invalid_argument','Unknown modifier')
                modifier={'none':None,'ctrl':29,'shift':42,'alt':56}.get(op.get('modifier','none'))
                if modifier:inputs.key(modifier,True)
                inputs.key(KEYS[op['key']],True);inputs.wait(hold_ms/1000);inputs.key(KEYS[op['key']],False)
                if modifier:inputs.key(modifier,False)
            else:
                text=op.get('text')
                require(isinstance(text,str) and text.isascii() and text.isprintable() and len(text)<=4096,
                        'unsupported_text','Use semantic input for Unicode')
                mapping=dict(LETTER_KEYS)
                mapping.update(dict(zip('1234567890',[2,3,4,5,6,7,8,9,10,11])));mapping[' ']=57
                require(all(c.lower() in mapping for c in text),'unsupported_text','Current keymap accepts letters digits and spaces')
                for char in text:
                    if char.isupper():inputs.key(42,True)
                    inputs.key(mapping[char.lower()],True);inputs.key(mapping[char.lower()],False)
                    if char.isupper():inputs.key(42,False)
            inputs.pump(.1)
        finally:inputs.close()
        return {'delivered':True,'verified_effect':False,'host_input_isolated':True,
                'input_scope':'private virtual compositor; its own focus/pointer may change'}
