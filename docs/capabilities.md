# Capabilities

The current [conformance matrix](conformance.md) records supported operations,
measured effects and limitations for X11, AT-SPI, private Wayland, headless CDP
and the experimental live Revu adapter.

No capability listing grants permission to operate a user's live application.
Fixtures use separate displays, profiles and buses. The private virtual seat can
change its own focus without targeting the user's seat. Live Revu requires
explicit configuration and a five-minute operator grant.

General control of arbitrary existing native Wayland apps, other Wine apps,
GPU overlays, games, password fields and every keyboard layout is not supported.
A successful event-delivery return must always be followed by effect inspection.
