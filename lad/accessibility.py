"""AT-SPI scoped to the launched PID on its private accessibility bus."""
import hashlib
import gi
from .errors import DesktopError, require

gi.require_version('Atspi', '2.0')
from gi.repository import Atspi
Atspi.set_timeout(1500, 2000)


class Accessibility:
    def __init__(self, pid):
        self.pid = pid

    def nodes(self):
        desktop = Atspi.get_desktop(0)
        found = []
        from collections import deque
        pending = deque()
        for i in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(i)
            if app and app.get_process_id() == self.pid:
                pending.append((app, str(i), 0))
        # Breadth-first traversal reaches visible controls before large hidden
        # command/menu subtrees consume the bounded result budget.
        while pending and len(found) < 1000:
            node, path, depth = pending.popleft()
            if depth > 16 or node.get_role() == Atspi.Role.PASSWORD_TEXT:
                continue
            role = node.get_role_name()
            name = node.get_name() or ''
            actions = node.get_action_iface()
            names = [actions.get_action_name(i) for i in range(actions.get_n_actions())] if actions else []
            signature = hashlib.sha256(f'{path}:{role}:{name}'.encode()).hexdigest()[:16]
            found.append((signature, node, {'element': signature, 'role': role, 'name': name,
                                          'actions': names, 'editable': node.get_editable_text_iface() is not None}))
            if role in ('menu', 'popup menu') and not node.get_state_set().contains(Atspi.StateType.SHOWING):
                continue
            for i in range(node.get_child_count()):
                child = node.get_child_at_index(i)
                if child:
                    pending.append((child, f'{path}/{i}', depth+1))
        return found

    def execute(self, op):
        nodes = self.nodes()
        if op['action'] == 'tree':
            return {'nodes': [n[2] for n in nodes], 'available': bool(nodes), 'scope': 'owned PID; password nodes excluded'}
        matches = [n for n in nodes if n[0] == op.get('element')]
        require(len(matches) == 1, 'stale_element', 'Reinspect the accessibility tree and select a current element')
        _, node, _ = matches[0]
        require(node.get_role() != Atspi.Role.PASSWORD_TEXT, 'protected_content', 'Password fields are excluded')
        if op['action'] == 'set_text':
            text = op.get('text')
            require(isinstance(text, str) and len(text) <= 4096, 'invalid_argument', 'Text must be at most 4096 characters')
            editable = node.get_editable_text_iface()
            require(editable is not None, 'unsupported_action', 'Element has no EditableText interface')
            require(editable.set_text_contents(text), 'action_rejected', 'Application rejected semantic text input')
        elif op['action'] == 'invoke':
            iface = node.get_action_iface()
            require(iface is not None, 'unsupported_action', 'Element has no Action interface')
            names = [iface.get_action_name(i) for i in range(iface.get_n_actions())]
            require(op.get('name', 'click') in names, 'unsupported_action', 'Requested action is not advertised by this element')
            require(iface.do_action(names.index(op.get('name', 'click'))), 'action_rejected', 'Application rejected action')
        else:
            raise DesktopError('unsupported_action', 'Unsupported semantic operation')
        return {'delivered': True, 'verified_effect': False}
