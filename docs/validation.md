# Validation record

The full release suite passed **37/37 cases in each of three fresh runs**: 111
passing executions. All rounds used the same recorded implementation/test
fingerprint. See [raw outcomes](../artifacts/conformance.json) and the
[capability matrix](conformance.md). Detailed JUnit and process logs remain
private under `.runtime/`.

The suite verifies application effects, image geometry/pixels, target identity,
ownership, locking, cancellation, idempotency, timeout semantics, observer
permissions and crash recovery. Native Wayland cases cover fractional scaling,
two virtual outputs, covered-window capture and unrelated input recipients.

The cursor tests move and resize an actual private KWin window, verify its
tracked client geometry, check an empty X11 input region and absent KDE shadow,
and confirm that active/idle transitions keep one persistent overlay window.
They also cover stale heartbeats, coordinate bounds, easing continuity and
explicit click events. Semantic buffer tests reject a concurrent edit without
overwriting it.

The portable test subset passed 13 cases locally. An Actions template is
included as `docs/checks-workflow.yml`; hosted CI is not yet enabled. The complete GUI suite needs the
system dependencies in README.md. One platform PyGI deprecation warning remains;
failures are not suppressed.

## Application demonstrations

- [Kate and Writer smoke checks](../artifacts/real-apps.json): fresh profiles on
  private Wayland, exact saved-text assertions, window capture, 1.5× scaling and
  two virtual outputs.
- [Live Kate demo](../artifacts/demo-kate.mp4): an ordinary desktop window,
  synthetic Python code, semantic range edits, application Save, exact buffer/file
  agreement, and five passing invoice-calculator tests. The code is in
  [examples/invoice_demo.py](../examples/invoice_demo.py). No global input is sent.
- [Earlier live Revu evidence](revu-live-test.md): three manually verified
  annotations on an explicitly authorized test document. No live Revu actions
  were repeated during public-release cleanup.

The six-path [capture benchmark](../artifacts/benchmark-expanded.json) records
60/60 successful captures. This is a small local benchmark, not a production SLO.

## Privacy and publication

Public artifacts omit local profile paths, document identifiers, observer access
links, process identifiers and private screenshots. Demo media contains only
synthetic source and owned demo tabs; it was reviewed before publishing.
Gitleaks and explicit path/file checks cover the release tree and outgoing
history. See [publication audit](../artifacts/publication-audit.json).

The original machine-specific brief is preserved only in a local backup. The
public repository begins with a new root commit. Runtime state, local client
configs, generated profiles, logs and dependency downloads are excluded.

## Limits

The shared live-window cursor is an operator prototype, separate from the MCP
fixture launch tools. A pointer indicator does not confer application control.
Live operations require explicit scope and usable application/accessibility APIs.
The accessibility bus was temporarily enabled for the live demo and its original
setting restored. The temporary capture permission and startup focus rule were
removed. Human and agent edits are not atomic; detected conflicts or partial
results require inspection. Universal live desktop control is not claimed.

## Dedicated Sway attachment on a server without a GPU

The [attachment report](../artifacts/attachment-conformance.json) records three
independent 5/5 runs with unchanged source fingerprints. It covers actual
Mousepad, Wine Notepad, the MCP bridge and failure/recovery paths. The
[server validation report](../artifacts/server-validation.json) distinguishes
observed application effects from exercised pointer-delivery paths.

The full suite on this server passes 37 cases and fails five private-KWin
ScreenShot2 capture cases. Running the untouched starting commit's KWin tests
on the same server yields the identical five failures and four passes. KWin's
virtual backend selects QPainter here; its screenshot implementation requires
an EGL backend. This pre-existing hardware/runtime limit does not affect Sway's
pixman capture path. The full suite is not reported as green.

Reproduce the new adapter independently with
`.venv/bin/python scripts/conformance.py --suite sway --rounds 3` after building
the native helper. Real apps use disposable documents, a fresh Wine prefix,
private D-Bus, fresh profiles and dedicated software-rendered outputs. Tests
leave attached applications running when their service grants are closed;
the test harness then shuts down only its own applications and compositor.
No Revu installation or license was available for a fresh Revu smoke check.
