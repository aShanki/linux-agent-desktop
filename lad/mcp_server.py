"""Identical MCP surface for Claude Code and Codex; daemon owns all application state."""
import asyncio
import anyio
import base64
import os
import uuid
from pathlib import Path
from typing import Any
from mcp.server.fastmcp import FastMCP, Image
from .protocol import request, DEFAULT_SOCKET

OWNER = os.environ.get('LAD_CLIENT_ID') or uuid.uuid4().hex
SOCKET = Path(os.environ.get('LAD_SOCKET', DEFAULT_SOCKET))
mcp = FastMCP('linux-agent-desktop', instructions=(
    'Use isolated fixtures or explicitly operator-enrolled live tasks only; never credentials. '
    'Call desktop_capabilities, open a task, discover a target, then act using a fresh action_id. '
    'Coordinates use the target-reported space. Inspect after writes: delivery does not prove effect. '
    'Never retry an unknown-effect write with a new ID. Close your task when done.'))

async def call(method, **params):
    operation = asyncio.create_task(asyncio.to_thread(request, method, params, owner=OWNER, path=SOCKET))
    try:
        result = await asyncio.shield(operation)
    except asyncio.CancelledError:
        # MCP cancellation has task-level semantics; the daemon owns the actual process.
        with anyio.CancelScope(shield=True):
            task_id = params.get('task_id')
            if method == 'open_task':
                opened = await operation
                task_id = opened.get('data', {}).get('task_id')
            if task_id:
                await asyncio.to_thread(request, 'cancel_task', {'task_id': task_id}, owner=OWNER, path=SOCKET)
        raise
    if not result['ok']:
        # Only structured, content-free service messages may reach the harness.
        raise ValueError(result['error']['code'] + ': ' + result['error']['message'])
    return result['data']

@mcp.tool(annotations={'readOnlyHint': True})
async def desktop_capabilities() -> dict[str, Any]:
    """Report actual backend support and restrictions without inspecting the host desktop."""
    return await call('capabilities')

@mcp.tool(annotations={'readOnlyHint': True})
async def desktop_tasks() -> dict[str, Any]:
    """List this client's tasks, including operator-enrolled live windows."""
    return await call('list_tasks')

@mcp.tool()
async def desktop_open_task(kind: str = 'qt', scale: float = 1, outputs: int = 1) -> dict[str, Any]:
    """Launch qt, gtk, browser, wayland-qt, wayland-gtk, or wayland-canvas on a private display. Never attaches to user apps."""
    return await call('open_task', kind=kind, scale=scale, outputs=outputs)

@mcp.tool(annotations={'readOnlyHint': True})
async def desktop_discover(task_id: str, action_id: str) -> dict[str, Any]:
    """List this task's owned windows and coordinate space; action_id is a unique request identifier."""
    return await call('act', task_id=task_id, action_id=action_id, action='discover')

@mcp.tool()
async def desktop_action(task_id: str, action_id: str, action: str, native_id: int | str,
                         args: dict | None = None, timeout: float = 8) -> dict[str, Any]:
    """Run a permitted action on an enrolled target. Use returned target ID and coordinates. Inspect to verify writes.

    Actions: geometry, tree, focus(), move(x,y), resize(width,height), click(x,y), type(text), key(key,modifier), scroll(x,y,steps),
    drag(x,y,end_x,end_y), set_text(element,text), invoke(element,name), dialog(accept).
    Non-success may have unknown effects; query desktop_result before any retry.
    """
    if action == 'screenshot':
        raise ValueError('Use desktop_screenshot for image content')
    return await call('act', task_id=task_id, action_id=action_id, action=action,
                      native_id=native_id, args=args or {}, timeout=timeout)

@mcp.tool(annotations={'readOnlyHint': True})
async def desktop_screenshot(task_id: str, action_id: str, native_id: int | str) -> Image:
    """Capture only the enrolled window, returning a PNG image in MCP content; never saved to the audit log."""
    value = await call('act', task_id=task_id, action_id=action_id, action='screenshot', native_id=native_id)
    if 'result' not in value:
        raise ValueError('Capture already completed; replay has metadata only. Use a fresh ID for a new read.')
    return Image(data=base64.b64decode(value['result']['png']), format='png')

@mcp.tool(annotations={'readOnlyHint': True})
async def desktop_result(action_id: str) -> dict[str, Any]:
    """Retrieve durable, content-free action status. Images, text and accessibility content are never persisted."""
    return await call('result', action_id=action_id)

@mcp.tool()
async def desktop_close_task(task_id: str) -> dict[str, Any]:
    """Cancel work; stop owned fixture processes or detach a live target without closing it."""
    return await call('close_task', task_id=task_id)


def main():
    mcp.run(transport='stdio')

if __name__ == '__main__':
    main()
