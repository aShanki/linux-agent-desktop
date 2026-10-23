# Live window indicator and Kate demo

The Kate demo records an ordinary window on the current desktop, using only
synthetic source code. D-Bus opens the owned file. AT-SPI selects and edits its
text, invokes Save, and reads the buffer back. A local subprocess runs five tests
against the file that Kate saved.

The video shows a failing baseline, a Decimal arithmetic fix, input validation,
saving, and five passing tests. It is not a claim that every Kate action works.
An earlier exploratory sidebar action timed out and is not counted as an
acknowledged successful operation.

The prototype indicator is deliberately separate from input delivery:

- One small, semi-transparent arrow, with no idle pulse or label.
- Ease-in-out motion between agent targets and a brief ripple for explicit clicks.
  Window translations and resizes track immediately rather than lagging behind.
- An empty X11 input region lets mouse input pass through.
- The KDE tooltip shadow is explicitly removed so there is no surrounding box.
- One persistent window remains mapped. Its opacity becomes zero while idle;
  it is not spawned and destroyed for each action.
- A two-second heartbeat expires stale activity after a controlling process fails.
- KWin reports the selected window's client geometry on movement and resizing.
  The indicator retains the stable window UUID and uses that current rectangle.

This is currently an **operator prototype**, not automatic enrollment of every
live application through MCP. An indicator can follow any selected KWin window;
actions still need a supported application adapter and authorization. Two agents
or a person and an agent cannot safely overwrite the same document just because
their pointer indicators are separate.

## Running the indicator

With an explicitly selected window UUID/PID and a private state-file path:

```sh
QT_QPA_PLATFORM=xcb .venv/bin/python -m lad.live_cursor \
  --window-id '{window-uuid}' --pid 1234 --state /private/path/cursor.json
```

Do not guess a window ID or scan private document contents to pick a target.
`WindowTracker` reads geometry, PID, minimized and active state, not captions or
screen contents. It installs a temporary KWin script for the selected UUID and
unloads it on graceful exit.

Wrap actual authorized GUI work with `lad.cursor_state.activity` to maintain
activity heartbeats. The state format supports explicit `window` pixel coordinates
and `normalized` coordinates. Window movement updates either mode. Resizing does
not authorize blindly scaling toolbar clicks: semantic targets need fresh bounds,
and out-of-bounds indicator coordinates are hidden rather than clamped.

Automated tests move and resize a real private KWin window, verify coordinate
projection and heartbeat expiration, and check that the overlay keeps the same
window ID with an empty input region across active/idle transitions.

During development a temporary no-focus rule was used to launch Kate without
activation. It was removed when the user requested normal shared interaction.
The runtime indicator does not install a focus-blocking rule.

The live Kate demonstration temporarily enabled the existing AT-SPI bus and
restored its original disabled setting afterward. No screen reader was started.
The `SemanticBuffer` helper validates a content fingerprint before each range
edit and verifies the result afterward. It detects ordinary concurrent changes,
but AT-SPI offers no atomic compare-and-swap against human typing; unknown or
partial effects require inspection, not an automatic retry.
