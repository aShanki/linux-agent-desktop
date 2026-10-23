/* A short-lived standard-US virtual keyboard for application shortcuts.
 * No uinput device, host display lookup, clipboard or shell execution. */
#define _GNU_SOURCE
#include <wayland-client.h>
#include <xkbcommon/xkbcommon.h>
#include <sys/mman.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "virtual-keyboard-unstable-v1-client-protocol.h"

static struct wl_seat *seat;
static struct zwp_virtual_keyboard_manager_v1 *manager;
static unsigned seats;
static void global(void *data, struct wl_registry *registry, uint32_t id,
                   const char *interface, uint32_t version) {
    (void)data; (void)version;
    if (!strcmp(interface, "wl_seat")) {
        seats++;
        if (!seat) seat = wl_registry_bind(registry, id, &wl_seat_interface, 1);
    } else if (!strcmp(interface, "zwp_virtual_keyboard_manager_v1")) {
        manager = wl_registry_bind(registry, id,
                   &zwp_virtual_keyboard_manager_v1_interface, 1);
    }
}
static void removed(void *data, struct wl_registry *registry, uint32_t id) {
    (void)data; (void)registry; (void)id;
}
static const struct wl_registry_listener listener = {global, removed};
static uint32_t milliseconds(void) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (uint32_t)(now.tv_sec * 1000 + now.tv_nsec / 1000000);
}
int main(int argc, char **argv) {
    if (argc != 3) return 2;
    int typing = !strcmp(argv[1], "--text");
    char *end;
    unsigned long code = typing ? 0 : strtoul(argv[1], &end, 10);
    if (!typing && (*end || code > 255)) return 2;
    const char *mod = argv[2];
    if (!typing && strcmp(mod,"none") && strcmp(mod,"ctrl") && strcmp(mod,"shift") && strcmp(mod,"alt")) return 2;
    struct wl_display *display = wl_display_connect(NULL);
    if (!display) return 3;
    struct wl_registry *registry = wl_display_get_registry(display);
    wl_registry_add_listener(registry, &listener, NULL);
    if (wl_display_roundtrip(display) < 0 || seats != 1 || !manager) return 3;
    struct xkb_context *context = xkb_context_new(XKB_CONTEXT_NO_FLAGS);
    if (!context) return 3;
    struct xkb_rule_names names = {.layout="us"};
    struct xkb_keymap *keymap = xkb_keymap_new_from_names(context, &names, XKB_KEYMAP_COMPILE_NO_FLAGS);
    if (!keymap) return 3;
    uint32_t codes[4096], masks[4096];
    size_t count = typing ? strlen(argv[2]) : 1;
    if (count == 0 || count > 4096) return 2;
    xkb_mod_index_t shift = xkb_keymap_mod_get_index(keymap, XKB_MOD_NAME_SHIFT);
    if (shift == XKB_MOD_INVALID || shift >= 32) return 3;
    if (typing) {
        for (size_t i = 0; i < count; i++) {
            unsigned char ch = (unsigned char)argv[2][i];
            if (ch > 127) return 2;
            xkb_keysym_t wanted = ch == '\n' ? XKB_KEY_Return : ch == '\t' ? XKB_KEY_Tab : xkb_utf32_to_keysym(ch);
            codes[i] = 0;
            for (xkb_keycode_t k = xkb_keymap_min_keycode(keymap); k <= xkb_keymap_max_keycode(keymap) && !codes[i]; k++) {
                for (xkb_level_index_t level = 0; level < 2; level++) {
                    const xkb_keysym_t *syms;
                    int n = xkb_keymap_key_get_syms_by_level(keymap, k, 0, level, &syms);
                    if (n == 1 && syms[0] == wanted) {
                        codes[i] = k - 8; masks[i] = level ? (1u << shift) : 0;
                        break;
                    }
                }
            }
            if (!codes[i]) return 2;
        }
    }
    char *text = xkb_keymap_get_as_string(keymap, XKB_KEYMAP_FORMAT_TEXT_V1);
    if (!text) return 3;
    size_t length = strlen(text) + 1;
    int fd = memfd_create("lad-keymap", MFD_CLOEXEC);
    if (fd < 0 || write(fd,text,length) != (ssize_t)length) return 3;
    struct zwp_virtual_keyboard_v1 *keyboard =
        zwp_virtual_keyboard_manager_v1_create_virtual_keyboard(manager, seat);
    zwp_virtual_keyboard_v1_keymap(keyboard, WL_KEYBOARD_KEYMAP_FORMAT_XKB_V1, fd, length);
    if (wl_display_roundtrip(display) < 0) return 3;
    close(fd); free(text);
    /* Let clients install the keymap before the first event. */
    usleep(100000);
    uint32_t mask = 0;
    if (!typing && strcmp(mod,"none")) {
        const char *name = !strcmp(mod,"ctrl") ? XKB_MOD_NAME_CTRL :
                           !strcmp(mod,"shift") ? XKB_MOD_NAME_SHIFT : XKB_MOD_NAME_ALT;
        xkb_mod_index_t index = xkb_keymap_mod_get_index(keymap, name);
        if (index == XKB_MOD_INVALID || index >= 32) return 3;
        mask = 1u << index;
    }
    if (!typing) { codes[0] = code; masks[0] = mask; }
    for (size_t i = 0; i < count; i++) {
        uint32_t modifier_code = typing ? (masks[i] ? 42 : 0) :
            !strcmp(mod,"ctrl") ? 29 : !strcmp(mod,"shift") ? 42 : !strcmp(mod,"alt") ? 56 : 0;
        if (modifier_code) {
            zwp_virtual_keyboard_v1_key(keyboard, milliseconds(), modifier_code, WL_KEYBOARD_KEY_STATE_PRESSED);
        }
        zwp_virtual_keyboard_v1_modifiers(keyboard, masks[i], 0, 0, 0);
        if (wl_display_roundtrip(display) < 0) return 3;
        usleep(2000);
        zwp_virtual_keyboard_v1_key(keyboard, milliseconds(), codes[i], WL_KEYBOARD_KEY_STATE_PRESSED);
        if (wl_display_roundtrip(display) < 0) return 3;
        zwp_virtual_keyboard_v1_key(keyboard, milliseconds(), codes[i], WL_KEYBOARD_KEY_STATE_RELEASED);
        if (modifier_code) {
            zwp_virtual_keyboard_v1_key(keyboard, milliseconds(), modifier_code, WL_KEYBOARD_KEY_STATE_RELEASED);
        }
        zwp_virtual_keyboard_v1_modifiers(keyboard, 0, 0, 0, 0);
        if (wl_display_roundtrip(display) < 0) return 3;
        usleep(2000);
    }
    usleep(20000);
    zwp_virtual_keyboard_v1_destroy(keyboard);
    zwp_virtual_keyboard_manager_v1_destroy(manager);
    wl_seat_destroy(seat);
    wl_registry_destroy(registry);
    wl_display_flush(display);
    wl_display_disconnect(display);
    xkb_keymap_unref(keymap); xkb_context_unref(context);
    return 0;
}
