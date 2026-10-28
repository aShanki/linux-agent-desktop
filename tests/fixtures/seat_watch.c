#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wayland-client.h>

static const char *output;
static void capabilities(void *data, struct wl_seat *seat, uint32_t caps) {
    char tmp[4096];
    snprintf(tmp, sizeof(tmp), "%s.tmp", output);
    FILE *file = fopen(tmp, "w");
    if (!file) exit(2);
    fprintf(file, "{\"pointer\":%s,\"keyboard\":%s}",
            caps & WL_SEAT_CAPABILITY_POINTER ? "true" : "false",
            caps & WL_SEAT_CAPABILITY_KEYBOARD ? "true" : "false");
    fclose(file);
    if (rename(tmp, output)) exit(2);
}
static const struct wl_seat_listener seat_listener = {.capabilities = capabilities};
static void global(void *data, struct wl_registry *registry, uint32_t name,
                   const char *interface, uint32_t version) {
    if (!strcmp(interface, "wl_seat")) {
        struct wl_seat *seat = wl_registry_bind(registry, name, &wl_seat_interface, 1);
        wl_seat_add_listener(seat, &seat_listener, NULL);
    }
}
static void removed(void *data, struct wl_registry *registry, uint32_t name) {}
static const struct wl_registry_listener registry_listener = {global, removed};
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    output = argv[1];
    struct wl_display *display = wl_display_connect(NULL);
    if (!display) return 2;
    struct wl_registry *registry = wl_display_get_registry(display);
    wl_registry_add_listener(registry, &registry_listener, NULL);
    while (wl_display_dispatch(display) >= 0) {}
    wl_display_disconnect(display);
    return 0;
}
