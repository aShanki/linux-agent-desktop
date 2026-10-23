# Experimental live Revu adapter

A manually authorized development test on a disposable PDF produced three red
annotations: a rectangle, ellipse and arrow. Existing annotations were preserved,
the document was not saved or reopened, and Hand mode was restored. The completed
actions reported unchanged Win32 foreground/cursor and XWayland focus/pointer.
One intermediate attempt stopped on the input-state guard; its transient cause
was not established. This is narrow evidence, not a universal no-focus guarantee.

Private document names, process/window identifiers, pointer positions and
screenshots are intentionally omitted from this public repository. This manual
evidence is separate from the reproducible isolated fixture tests. The original
manual test predates the release's explicit environment configuration; the live
application was not manipulated again during release validation.

## Mechanism and boundaries

The driver resolves nested WinForms child windows, translates coordinates and
uses bounded `WM_MOUSEMOVE`, `WM_LBUTTONDOWN` and `WM_LBUTTONUP` messages. It does
not call `SetCursorPos`, `SendInput`, `SetFocus`, `SetForegroundWindow` or XTest.
The Python backend pins the Linux process start time and XID; the helper pins
the Win32 HWND/PID and configured document-title match. Ambiguous titles reject.

A changed input-state guard revokes enrollment. Multi-message actions can still
have partial effects. Capture requires the mapped, supported 24-bit XWayland
visual. Unmapped windows, other Wine applications and general Wayland surfaces
are not validated. Coordinate input cannot infer whether an arbitrary button is
sensitive or destructive; stay within the authorized markup workflow.

## Configure and enroll

Set `LAD_WINE_BIN`, `LAD_WINEPREFIX` and `LAD_REVU_TITLE` before daemon startup.
There are no machine-specific or implicit Wine profile defaults. Missing
configuration rejects enrollment before desktop inspection. See
[usage](usage.md#live-revu-test-adapter) for complete commands.

The operator can enroll one client for five minutes; public MCP tools cannot
silently grant themselves a live target. `revoke-all` or `desktop_close_task`
detaches without closing the application or killing its Wine server. This is an
operator consent workflow, not a defense against malicious same-user shell code.

Implementation: `lad/live_revu.py` and `lad/native/revu-{control,probe}.c`.
Native helpers compile during enrollment using `x86_64-w64-mingw32-gcc`.
Automated policy/configuration tests use surrogates and do not contact Revu.

The implementation follows Microsoft's [window-message parameter contract](https://learn.microsoft.com/en-us/windows/win32/inputdev/wm-lbuttondown)
and [bounded message delivery API](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendmessagetimeoutw).
Application effects must be verified separately from API return values.
