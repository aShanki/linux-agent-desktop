# Architecture and decisions

The service supports isolated fixtures and explicit live-window grants. The
[Sway attachment](sway-attachment.md) adds a compositor-specific path for real
native Wayland and Wine/Xwayland applications. The initial fixture decisions
below describe the default isolation boundary; Sway enrollment is a separate scope.
It exposes a provider-neutral Unix-socket service through an official-SDK MCP
stdio bridge. Both Claude Code and Codex use the same actions and policy.

## Runtime

`Claude/Codex → MCP stdio bridge → same-UID Unix socket → task policy + journal → adapter`

Each task owns a private Xvfb display, freshly generated display authorization,
private D-Bus session, fresh HOME/XDG directories, and one allowlisted fixture.
Qt and GTK use short-lived adapter processes with bounded lifetimes. The browser
uses a persistent CDP worker to preserve dialog state between actions. No child
inherits the user's DISPLAY, WAYLAND_DISPLAY, XAUTHORITY, DBus address, profile,
or other arbitrary environment variables. Live Sway attachment uses a separate operator-only grant and does not inherit these fixture permissions.

The service is bound to one runtime directory with `flock`; socket directory mode
0700 and socket mode 0600, plus `SO_PEERCRED`, restrict access to the same OS user.
A task owner ID prevents accidental cross-client operations; **it is not a security
boundary against another process running as that same user**. Configured owner IDs
are stable per harness for durable result retrieval across client restarts. Clients
within that harness share the owner namespace; task IDs still distinguish work.

Only this project's fixture launch templates are implemented; live attachment does not launch applications. Private HOME and
display are focus/profile isolation, **not a filesystem or network sandbox**.
Attached apps remain outside a sandbox and require the dedicated-session enrollment policy.
The service can read its own fixture state and log files, not account credentials.
The synthetic fixture's `fixture.json` intentionally records its non-sensitive
input for benchmark assertions; never enter real secrets in these fixtures.

## ADR 001: explicit isolation before host injection

Wayland gives compositors ownership of surface placement and input routing. A
client cannot assume global discovery, capture or background injection into another
client. Portals and KWin-specific integration are separate, consent-sensitive
backends, not automatic fallbacks. No global KWin changes, XTest calls, pointer
warps, clipboard access, host captures, or focus activation occur here.

XSendEvent delivers directly to an owned X11 window; acceptance depends on the
application. A Qt click can activate that app **inside its isolated display**.
The response distinguishes `isolated_display_focus_unchanged`,
`pointer_unchanged`, and `host_input_isolated`. These are not interchangeable.
Host Wayland focus is protected structurally by having no connection to it, not
claimed as measured through an unavailable compositor-wide API.

## ADR 002: semantic and browser actions are separate backends

GTK uses AT-SPI on the task's private bus, scoped to the launched PID. Element
handles bind a traversal path, role and name; stale handles fail. Traversals are
bounded to 300 nodes and depth 16, and password nodes are omitted. An empty tree
is a valid unsupported result, observed for this Qt build. AT-SPI node handles
are best-effort snapshots, not immutable app object identities.

The browser is a new headless Chrome process with a fresh profile, ephemeral
loopback port and the local fixture URL. CDP discovery rejects other URLs;
there is no user-provided endpoint, arbitrary JavaScript, cookie, navigation or
profile API. A persistent connection handles JavaScript dialogs without losing
them when a per-action worker disconnects. Browser text uses Input.insertText,
not clipboard mutation. DOM descriptions exclude password inputs.

The original fixture-only Wine extension was unvalidated; subsequent Revu and
Sway/Wine adapters have separate grants and evidence. The existing Revu sign-in helper
was read as source only; its session/port/profile were never contacted. Its
cross-process painting limitation is one reason capture support must be proved
per application. Those initial observations do not establish support for new Wine applications.

## ADR 003: failures must not silently replay writes

One action lock per task returns `busy` immediately on concurrent access;
different tasks can proceed concurrently. Each action has a client-supplied ID.
Before execution, SQLite commits `running`; after execution it commits a safe
summary. Repeated IDs return metadata without re-execution. A changed payload
conflicts. HMAC request fingerprints use an ephemeral service key, preventing
offline guessing of typed text from the journal. After restart, old task handles
are invalid and running records become `interrupted`; completed summaries remain
queryable. Restart does not silently resume automation.

Timeout/cancellation/backend loss means **unknown effect**, not guaranteed rollback.
Inspect before another write. Process groups are owned and tracked with PID start
times; recovery kills only matching groups from private task manifests. MCP cancellation forwards to task cancellation. A 30-minute
task lease, a six-active-task limit, and a local `revoke-all` command provide
bounded ownership. Cancellation terminates owned groups; it does not undo completed
application operations. There is no transaction claim for multi-event gestures.

## ADR 004: consent and sensitive actions fail closed

Opening a known fixture is the explicit scope grant. Operations outside the
allowlist, external/destructive actions, credentials and foreground fallback are
unsupported and rejected. There is deliberately no agent-provided `approved=true`
flag. A future foreground backend must use a distinct operator-approved, scoped,
expiring grant and define rollback of settings changes before it is enabled.
No such settings changes are needed by this version.

## ADR 005: a visual cursor does not require moving the real pointer

The observer is a read-only loopback HTTP service protected by an ephemeral
capability in the URL fragment and Authorization header. Host and Origin checks
reject cross-site reads; no write endpoints or permissive CORS exist. The URL is
saved mode 0600 in `.runtime/observer-url`. Treat it as a private viewing link.
Images and action coordinates stay in memory; the observer retains at most 12 task previews. The UI uses an SVG cursor, smooth
motion, click rings, drag trails, activity status and reduced-motion preferences.
It animates **requested action coordinates**, not hardware-pointer movement or
proof that an application accepted an event. Text payloads never enter the activity
feed. Screenshots can visibly contain entered fixture text.

Snapshots are refreshed on writes/capture, not continuously streamed video.
Semantic operations may not have a coordinate, so their activity is shown without
inventing a pointer location. A separately granted host overlay remains future work.

## ADR 006: an explicitly authorized live Revu scope

A later user request granted control of the running Revu sample document. This
adds a separate `LiveRevu` session class and operator-only CLI enrollment. It uses
the existing Wine session without adopting Revu's process lifetime. Only helper
processes are owned; close/revoke/expiry never closes Revu or its document.
Live grants expire after five minutes and cannot overlap. The helper performs
native child-window message delivery, bounded by timeouts, exact title/HWND/PID
checks and foreground/pointer guards. Capture and the Python guard use only the
enrolled X11 window and raw input-state identifiers. Typing and arbitrary live
application attachment remain disabled. See `revu-live-test.md` for observed
success and the guard-interrupted attempt. Earlier fixture-only decisions remain
the default, rather than a prohibition on subsequently authorized adapters.

## ADR 007: generic native input belongs to a private compositor

The broader validation work adds native Wayland fixtures to private virtual KWin
sessions. EIS/libei provides a real virtual input seat; ScreenShot2 captures a
window by KWin UUID even when covered. Private-bus owner PID checks prevent the
adapter from accidentally reaching the user's compositor. Window hit-testing
rejects covered coordinate targets rather than silently inputting into another
window. Semantic GTK operations remain available under occlusion without changing
that private compositor's active foreground window. Tests also check an independent
X server's focus/pointer and app state while the virtual Wayland seat is active.
See conformance.md for the exact distinction between no host-focus changes and
allowed focus changes inside an isolated task.

## Release hardening

Live Revu configuration has no implicit profile or document defaults: the
operator supplies `LAD_WINE_BIN`, `LAD_WINEPREFIX` and `LAD_REVU_TITLE` before
service startup. Missing values reject before inspecting a desktop. Native
helpers receive the same explicitly selected title through their environment.

Recovery waits for signalled owned processes to stop before accepting requests.
Signal delivery alone does not imply process termination; a bounded failure
aborts startup and leaves the manifest available for recovery.
