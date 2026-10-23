# Attach real Wayland and Wine applications on Sway

The `sway-live` adapter attaches an already-running application in an explicitly
configured, dedicated Sway session. It uses Sway IPC for stable container IDs,
window geometry, focus and pointer events; virtual-keyboard for text/shortcuts;
and grim/screencopy for visible-region screenshots. Wine windows running through
that session's Xwayland use the same path. No application-specific instrumentation,
accessibility tree, Wine prefix access or test-document title is required.

This is a compositor-specific implementation. Existing host KWin, GNOME/Mutter,
Hyprland, X11-only desktops and applications in other sessions are not attachment
backends. The private KWin fixture backend remains separate.

## Operator configuration and grant

Install Sway, grim, wtype, and the native helper's build dependencies (C compiler,
pkg-config, libwayland-dev, libwayland-bin and libxkbcommon-dev). From the source
checkout run:

```sh
./scripts/bootstrap.sh
./scripts/build-sway-helper.sh
```

Choose the **dedicated session**, then set all three values explicitly in the
service's environment. The service does not adopt SWAYSOCK, WAYLAND_DISPLAY or
XDG_RUNTIME_DIR from its inherited desktop environment:

```sh
export LAD_SWAYSOCK=/absolute/path/to/dedicated/sway-ipc.sock
export LAD_XDG_RUNTIME_DIR=/absolute/path/to/dedicated/runtime
export LAD_WAYLAND_DISPLAY=wayland-1
.venv/bin/lad serve
```

IPC and Wayland sockets must be owned by the service user and connected to the
same compositor PID/start time. Exactly one seat named `seat0` is supported.
No compositor security settings are changed. Missing input/capture protocols
fail with a backend error; there is no global-input fallback.

The local operator, in another terminal, lists candidates and selects the exact
container ID and PID. Titles are shown to the operator but are never selectors.
Use the same `--owner` as the MCP bridge's `LAD_CLIENT_ID`:

```sh
.venv/bin/lad sway-targets
.venv/bin/lad --owner codex-linux-agent-desktop attach-sway \
  --native-id 42 --pid 1234 --consent-session
```

`--consent-session` grants five minutes of exclusive input and visible capture
in this dedicated session. The operator must control what other applications,
panels and overlays can appear there. The session pointer and focus may move.
This grant is unsuitable for concurrent human work in the same session. It
cannot move a running app out of another compositor or isolate a shared desktop.
MCP clients cannot issue the enrollment/listing methods through MCP tools.
The same-UID operator socket remains a coordination boundary, not protection
against malicious processes running as the operator.

## MCP actions

`desktop_tasks` finds the enrolled task; `desktop_discover` returns only its
selected window. `desktop_action` accepts the stable returned native ID:

- `focus`: explicitly focus the selected window. Keyboard, pointer input and
  screenshot require it already focused and fail if focus leaves it.
- `geometry`: current content rectangle in logical pixels. Discovery also reports
  the outer container rectangle. Coordinates for input are content-relative.
- `type(text)`: up to 4096 characters, no clipboard use. ASCII uses the standard
  US virtual keyboard; native Wayland Unicode uses wtype. Wine/Xwayland Unicode
  is explicitly rejected because it has not been validated.
- `key(key, modifier)`: standard US virtual-keyboard mapping. Supported keys are
  Return, Tab, Escape, BackSpace, Delete, arrows, Home, End, a, s, z, c and v;
  modifiers are none, ctrl, shift and alt. Other layouts/IMEs are not established.
- `click(x,y)`, `drag(x,y,end_x,end_y)`, `scroll(x,y,steps)`: logical content
  coordinates; endpoints must remain inside the selected window. Pointer movement
  is visible in the enrolled session. Scroll steps are limited to 20.
- `move(x,y)`, `resize(width,height)`: already floating windows only, bounded
  integer coordinates/sizes. These never convert a tiled window to floating.
- `desktop_screenshot`: visible content rectangle at one pixel per logical pixel,
  limited to 16 million pixels. A moved window's capture is discarded. This can
  include overlapping session surfaces. It is **not** an occlusion-independent
  or security-filtered window capture.

AT-SPI, semantic actions, native app dialogs, arbitrary keys, close/kill, launch,
save-document APIs, password automation and authentication are not supplied by
this adapter. A Save shortcut can be sent within the enrolled disposable document,
but callers must independently verify the file or application state.
Dialogs are separate containers and require explicit re-enrollment. If a modal
dialog takes focus, input stops rather than following it automatically.

## Failure and lifetime rules

A seat lease spans service roots and window IDs. Enrollment fails if another
live task owns that compositor. It binds socket inodes, compositor PID/start time,
target PID/start time and container ID. Window moves/resizes preserve the ID;
replacement windows and restarted processes require another operator grant.

Actions use the existing task lock and metadata-only idempotency journal. Helpers
are short-lived process groups; their manifests allow restart recovery to kill
only matching helpers. Revocation, close, expiry and restart never kill an attached
application or compositor. Restart invalidates all task handles and releases an
interrupted pointer press only after acquiring the previous compositor's seat
lease. Recovery refuses a mismatched configured compositor while the old one lives.

Timeout, backend loss, target loss or focus change revoke the grant. Interrupted
writes have unknown effects and must be inspected before another write. Focus is
checked before/after operations and every 20 ms while helpers run, but the check
and input are not atomic. Dedicated-session exclusivity is required: a compositor
binding, popup, overlay or another participant can still redirect an event between
checks. No rollback or protection against concurrent human typing is promised.

## Reproduce real-application checks

Install Mousepad, Wine 64-bit, Xwayland and dbus-daemon as well as the dependencies
above. Run:

```sh
LAD_TEST_SWAY=1 .venv/bin/python -m pytest tests/test_sway.py -v
```

Tests start a fresh two-output headless Sway using the pixman software renderer,
a private bus and fresh HOME/Wine prefix. They enroll independently started
Mousepad and Wine Notepad windows through the service, type and save scratch
files, read the saved output independently, and decode actual screenshot PNGs.
They also exercise geometry changes, pointer actions, focus-loss rejection,
ownership contention, replay, timeout, cancellation and crash recovery.
No GPU, host desktop, personal profile or licensed Revu installation is required.
Revu compatibility is not inferred from Notepad: the existing opt-in Revu adapter
and its separately recorded evidence remain available.

Protocol contracts are in [Sway IPC](https://github.com/swaywm/sway/blob/master/sway/sway-ipc.7.scd),
[Sway seat commands](https://github.com/swaywm/sway/blob/master/sway/sway-input.5.scd),
[wtype](https://github.com/atx/wtype) and the vendored MIT-licensed
[virtual keyboard protocol](../lad/native/virtual-keyboard-unstable-v1.xml).
