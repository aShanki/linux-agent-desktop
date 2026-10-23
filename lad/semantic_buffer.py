"""Scoped AT-SPI text edits with optimistic conflict detection.

This does not create consent or lock out human input. The caller must enroll the
PID/element and stop after conflicts or unknown effects; AT-SPI edits are not an
atomic compare-and-swap with human typing.
"""
import hashlib
from .accessibility import Accessibility, Atspi
from .errors import DesktopError, require


def fingerprint(text):
    return hashlib.sha256(text.encode()).hexdigest()


class SemanticBuffer:
    def __init__(self, pid, element):
        matches = [(node, info) for ident, node, info in Accessibility(pid).nodes() if ident == element]
        require(len(matches) == 1, 'stale_element', 'Reinspect the enrolled text element')
        self.node, info = matches[0]
        require(info['editable'] and self.node.get_role() != Atspi.Role.PASSWORD_TEXT,
                'protected_content', 'Only an explicitly selected editable text element is permitted')
        require(self.node.get_text_iface() is not None, 'unsupported_action', 'Element has no text interface')

    def read(self):
        require(not self.node.get_state_set().contains(Atspi.StateType.DEFUNCT),
                'stale_element', 'Enrolled text element is gone')
        return Atspi.Text.get_text(self.node, 0, -1)

    def replace(self, start, end, replacement, expected):
        before = self.read()
        require(fingerprint(before) == expected, 'concurrent_edit', 'Text changed; inspect before editing')
        require(type(start) is int and type(end) is int and 0 <= start <= end <= len(before),
                'out_of_bounds', 'Text edit range is outside the current buffer')
        require(isinstance(replacement, str) and len(replacement) <= 4096,
                'invalid_argument', 'Replacement must be at most 4096 characters')
        if end > start:
            require(Atspi.EditableText.delete_text(self.node, start, end), 'unknown_effect', 'Deletion was not acknowledged')
        if replacement:
            require(Atspi.EditableText.insert_text(self.node, start, replacement, len(replacement)),
                    'unknown_effect', 'Insertion was not acknowledged; inspect before retrying')
        after = self.read()
        require(after == before[:start] + replacement + before[end:],
                'unknown_effect', 'Text changed during the edit; inspect before retrying')
        return {'fingerprint': fingerprint(after), 'characters': len(after)}
