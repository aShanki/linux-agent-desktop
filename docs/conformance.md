# What the no-focus claim means, and how to test it

The deliverable is a reproducible compatibility boundary, not a claim about every
possible application. A successful event-send return is not proof. Each tested
operation must produce an independently observed application effect and leave
unrelated input recipients alone. Tests do not control the user's live desktop.

## Implemented paths

| Path | Operations with effect assertions | Input isolation | Tested boundaries |
|---|---|---|---|
| Qt on private X11 | Text/punctuation, selection replacement, clicks, drag selection, PNG pixels | Separate X server | 1×, 1.5×, 2×; directed wheel remains unsupported |
| GTK on private X11 | Unicode EditableText and Action.click | Private accessibility bus | Stale semantic handles reject |
| Qt on private KWin/Wayland | Click, keyboard, selection, text, wheel, drag, native dialog | Separate compositor and virtual input seat | 1×, 1.5×, 2×, two virtual monitors |
| GTK on private KWin/Wayland | Coordinate and semantic text/clicks, PNG | Separate compositor/bus | Covered-window Unicode and button invocation preserve the active sentinel |
| Custom-painted Qt canvas on private Wayland | Stroke geometry, keys, wheel, pixel capture | Separate compositor and virtual input seat | Does not rely on semantic controls |
| Headless Chrome | Unicode text, click count, wheel, modal dismiss, PNG | Dedicated process/profile/CDP target | Browser target identity checked |
| Live Revu in Wine | Real rectangle, ellipse, arrow, Hand mode, PNG | Direct Win32 child-window messages and input-state guards | Explicit five-minute sample-document grant; manual evidence in revu-live-test.md |

## Original recorded outcome

Three complete independent rounds passed: **37/37, 37/37, 37/37**.
Raw cases, durations and outcomes are in [`artifacts/conformance.json`](../artifacts/conformance.json)
with private JUnit/log files generated under `.runtime/`.
All three final rounds include the stricter covered-window pixel comparison
and a counter for every sentinel foreground-loss event. The report records a
SHA-256 fingerprint of the tested implementation and tests, and checks that it
remained unchanged throughout each round.

## Regression gates

- Compare fixture state to expected text, click count, selection, stroke endpoints,
  scroll position and dialog state. A transport acknowledgement is insufficient.
- Check PNG geometry and known marker colors. Capture a fully covered GTK window
  and confirm it is not the magenta covering window.
- Keep an opaque sentinel foreground in the same private compositor while GTK
  semantic operations run underneath. Assert its focus stays active and its key
  and click counters stay zero.
- Keep another application's input focus in a separate private X server while
  Wayland input runs. Assert that server's focus, pointer and fixture state stay
  unchanged.
- Reject covered coordinate targets rather than deliver to the wrong window.
- Verify independent tasks, lock contention, idempotency conflicts, ownership,
  timeouts, active cancellation, daemon crash recovery and live-grant revocation.
- Refuse to initialize the KWin backend without its private runtime marker and
  matching compositor PID on the private D-Bus connection.

Run `.venv/bin/python scripts/conformance.py --rounds 3`. It runs fresh complete
suites, writes private per-round JUnit files and a public metadata-only aggregate `artifacts/conformance.json`,
and fails immediately if any round fails. This is deliberately repeatable rather
than one recorded visual success.

## Platform implementation

Private KWin is launched with `--virtual` and an isolated D-Bus, runtime, home and
configuration. No DISPLAY or host Wayland connection is inherited. Its runtime
socket has a short private temporary path to avoid the Unix socket path-length
limit. `kscreen-doctor` configures scale and output placement only inside that
private session. The `--scale` startup flag alone changes framebuffer size but
does not establish the reported output scale; the tests caught this distinction.

The adapter uses KWin's EIS interface with libei for input, and its ScreenShot2
interface for window capture. The caller verifies the private compositor PID
before using either. Screenshot permission checks are disabled only in the new,
service-owned private compositor process; no setting on the user's compositor is
changed. Window discovery is PID-scoped and capture uses stable KWin window UUIDs.

The private seat's focus and pointer may move. The user's seat is a different
compositor connection and is never the target. This is a useful application
isolation route, not a technique for silently moving an already running native
Wayland window out of the user's compositor.

Primary interfaces:
[KWin EIS source](https://github.com/KDE/kwin/blob/v6.6.6/src/plugins/eis/eisbackend.cpp),
[KWin screenshot source](https://github.com/KDE/kwin/blob/v6.6.6/src/plugins/screenshot/screenshotdbusinterface2.cpp),
[KWin scripting workspace](https://github.com/KDE/kwin/blob/v6.6.6/src/scripting/workspace_wrapper.h).

## What remains outside the evidence

Outside the explicitly enrolled dedicated Sway session, an arbitrary
already-running native Wayland custom canvas is not covered. A
client may expose no usable accessibility interface or application automation
API, and the compositor routes ordinary input to its selected surface. Moving a
private seat does not inject into an arbitrary host surface. Existing apps need
an explicitly authorized semantic/application-specific route, or must be launched
in isolation. Wine applications outside the new Sway/Xwayland path, GPU overlays, games, multi-seat hardware,
password input, and prolonged production workloads are not established by this
suite. The hardware monitor layout is not changed; two-monitor tests use virtual
outputs. A passing sample suite is not a universal compatibility proof.

## Capture benchmark

`artifacts/benchmark-expanded.json` records **60/60** successful captures, ten
per backend. Median times were 112.32 ms (Qt/X11), 122.74 ms (GTK/X11), 33.45 ms
(CDP), 87.14 ms (Qt/Wayland), 88.20 ms (GTK/Wayland) and 83.16 ms (custom canvas).
These are local smoke benchmarks, not production latency guarantees.

Native Wayland keyboard text supports printable US ASCII on the private
compositor's default keymap. GTK semantic input and CDP cover Unicode.
Other keyboard layouts, control characters and IMEs remain unsupported here.

## Installed applications, separate smoke checks

`artifacts/real-apps.json` records passing checks for **Kate 25.12.3** and
**LibreOffice Writer 26.2.6.3**. Both ran on private native Wayland with 1.5×
scaling and two virtual outputs. The script types a fixed sentence, invokes
Ctrl+S, independently reads the scratch document and requires an exact match,
then captures the application window. Writer's fresh-profile welcome dialog
is dismissed with Escape before typing. The host applications are never targeted.

Run `.venv/bin/python scripts/real_apps.py` to reproduce these two checks.
They are separate from the 28-case regression suite. These are backend smoke
checks, not additional public MCP task kinds or general live-app enrollment.

Initial exploration found and resolved the installed Writer build's need for
`SAL_USE_VCLPLUGIN=qt6`, its startup dialog, and changing splash-window identity.
Kate detaches from its launcher, so the script resolves its PID through the
private D-Bus service rather than guessing from the launcher PID. No failed
exploratory attempt is counted as a passing run.

## Public release additions

The release suite includes explicit live-adapter configuration checks, a
signal-driven live-window tracker, an input-transparent persistent cursor,
active/idle heartbeat expiry, smooth movement and click-event state, and scoped
semantic buffer edits with conflict detection. The complete suite passed
**111 test executions** across three fresh runs.

The separate [live Kate demo](../artifacts/demo-kate.mp4) edits a synthetic invoice
calculator in an ordinary desktop window using AT-SPI, saves through Kate, and
runs five passing tests against the saved file. It is not a general live-window
MCP enrollment or a guarantee of atomic edits alongside human typing.

## Real Sway attachment

The new [Sway attachment suite](sway-attachment.md) tests independently started
Mousepad and Wine Notepad through service enrollment, exact saved scratch output,
actual PNG capture and safety/failure paths. It runs only with `LAD_TEST_SWAY=1`.
The historical counts above predate this adapter. Current outcomes and source
fingerprints are recorded in the generated conformance report. A separate Revu
installation is not present in this server test environment.

The final Sway attachment run passed **5/5 in each of three rounds**. See the
[attachment report](../artifacts/attachment-conformance.json) and
[server validation details](validation.md#dedicated-sway-attachment-on-a-server-without-a-gpu).
The GPU-less server's five pre-existing KWin capture failures are recorded
separately; they are not counted as passing tests.
