#!/usr/bin/env python3
"""A wrapped, clickable tab list displayed in a Herdr split pane."""

import curses
import fcntl
import json
import os
import pathlib
import re
import select
import socket
import sys
import time
import unicodedata


PLUGIN_ID = "local.wrapped-tabs"
BAR_TITLE = "Wrapped tabs"
PLUGIN_ROOT = pathlib.Path(__file__).resolve().parent
STATE_DIR = pathlib.Path(os.environ.get("HERDR_PLUGIN_STATE_DIR", pathlib.Path.home() / ".config/herdr/plugins/state/local.wrapped-tabs"))
STATE_FILE = STATE_DIR / "workspaces.json"
LOCK_FILE = STATE_DIR / "workspaces.lock"
SOCKET_PATH = os.environ.get("HERDR_SOCKET_PATH", str(pathlib.Path.home() / ".config/herdr/herdr.sock"))
MOUSE_EVENT = re.compile(rb"^\x1b\[<(\d+);(\d+);(\d+)([Mm])")
KEY_SEQUENCES = {
    b"\x1b[A": "up",
    b"\x1b[B": "down",
    b"\x1b[C": "right",
    b"\x1b[D": "left",
    b"\x1b[5~": "page_up",
    b"\x1b[6~": "page_down",
}


def request(method, params=None):
    message = {"id": "wrapped-tabs", "method": method, "params": params or {}}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(3)
        connection.connect(SOCKET_PATH)
        connection.sendall((json.dumps(message) + "\n").encode())
        with connection.makefile("r", encoding="utf-8") as stream:
            response = json.loads(stream.readline())
    if "error" in response:
        raise RuntimeError(f"{method}: {response['error']}")
    return response["result"]


def snapshot():
    return request("session.snapshot")["snapshot"]


def read_state():
    if not STATE_FILE.exists():
        return {"disabled": [], "panes": {}, "suspended": False}
    try:
        data = json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {"disabled": [], "panes": {}, "suspended": False}
    return {"disabled": data.get("disabled", []), "panes": data.get("panes", {}), "suspended": data.get("suspended", False)}


def write_state(state):
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n")
    temporary.replace(STATE_FILE)


def lock_state():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    lock = LOCK_FILE.open("w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    return lock


def cell_width(value):
    return sum(2 if unicodedata.east_asian_width(char) in "WF" else 0 if unicodedata.combining(char) else 1 for char in value)


def clean_label(value):
    return "".join(char if char.isprintable() and char not in "\r\n\t" else " " for char in value).strip()


def tab_cells(tabs, width):
    width = max(width, 4)
    cells = []
    for tab in tabs:
        label = f"{tab['number']} {clean_label(tab['label'])}"
        while cell_width(label) > width - 2 and len(label) > 1:
            label = label[:-1]
        cells.append((tab["tab_id"], f" {label} "))
    return cells


def place_cells(cells, width):
    positions = []
    row = 0
    column = 0
    for tab_id, label in cells:
        length = cell_width(label)
        if column and column + length > width:
            row += 1
            column = 0
        positions.append((tab_id, label, row, column, length))
        column += length + 1
    return positions


def desired_height(required_rows, available_height):
    minimum = max(4, round(available_height * 0.1))
    maximum = max(minimum, available_height // 2)
    return min(max(required_rows + 2, minimum), maximum)


def resize_bar(pane_id, tab_id, required_rows):
    layout = request("pane.layout", {"pane_id": pane_id})["layout"]
    if layout["tab_id"] != tab_id or len(layout["panes"]) != 2 or len(layout["splits"]) != 1:
        return
    height = layout["area"]["height"]
    if height < 8:
        return
    desired = desired_height(required_rows, height)
    current = next((pane["rect"]["height"] for pane in layout["panes"] if pane["pane_id"] == pane_id), 0)
    if abs(current - desired) > 1:
        request("layout.set_split_ratio", {"tab_id": tab_id, "path": [], "ratio": desired / height})


def open_bar(tab_id, target_pane_id, workspace_tabs, layout):
    response = request("plugin.pane.open", {
        "plugin_id": PLUGIN_ID,
        "entrypoint": "bar",
        "placement": "split",
        "target_pane_id": target_pane_id,
        "direction": "down",
        "focus": False,
    })
    pane = response.get("pane") or response.get("plugin_pane", {}).get("pane", {})
    pane_id = pane.get("pane_id") or response.get("pane_id")
    if not pane_id:
        updated = snapshot()
        added = [item["pane_id"] for item in updated["panes"] if item["tab_id"] == tab_id and item["pane_id"] != target_pane_id]
        if len(added) != 1:
            raise RuntimeError(f"Cannot identify new bar pane in {tab_id}: {response}")
        pane_id = added[0]
    request("pane.swap", {"source_pane_id": pane_id, "target_pane_id": target_pane_id})
    width = max(layout["area"]["width"] - 2, 4)
    positions = place_cells(tab_cells(workspace_tabs, width), width)
    resize_bar(pane_id, tab_id, max((position[2] for position in positions), default=0) + 1)
    return pane_id


def sync_locked(state):
    current = snapshot()
    original_tab_id = current["focused_tab_id"]
    original_pane_id = current["focused_pane_id"]
    panes = {pane["pane_id"] for pane in current["panes"]}
    tabs = {tab["tab_id"]: tab for tab in current["tabs"]}
    state["panes"] = {tab_id: pane_id for tab_id, pane_id in state["panes"].items() if tab_id in tabs and pane_id in panes}
    if state["suspended"]:
        write_state(state)
        return
    layouts = {layout["tab_id"]: layout for layout in current["layouts"]}
    for tab in current["tabs"]:
        tab_id = tab["tab_id"]
        if tab["workspace_id"] in state["disabled"] or tab_id in state["panes"]:
            continue
        layout = layouts.get(tab_id)
        if not layout or len(layout["panes"]) != 1 or layout.get("zoomed"):
            continue
        target = layout["panes"][0]["pane_id"]
        workspace_tabs = [item for item in current["tabs"] if item["workspace_id"] == tab["workspace_id"]]
        pane_id = open_bar(tab_id, target, workspace_tabs, layout)
        state["panes"][tab_id] = pane_id
        write_state(state)
        request("pane.focus_direction", {"pane_id": pane_id, "direction": "down"})
    write_state(state)
    if original_tab_id and original_tab_id in tabs:
        request("tab.focus", {"tab_id": original_tab_id})
        focused_pane_id = snapshot()["focused_pane_id"]
        if focused_pane_id != original_pane_id and focused_pane_id in state["panes"].values():
            request("pane.focus_direction", {"pane_id": focused_pane_id, "direction": "down"})


def enable():
    workspace_id = os.environ.get("HERDR_WORKSPACE_ID") or snapshot()["focused_workspace_id"]
    if not workspace_id:
        raise RuntimeError("No active Herdr workspace")
    with lock_state():
        state = read_state()
        state["disabled"] = [item for item in state["disabled"] if item != workspace_id]
        state["suspended"] = False
        write_state(state)
        sync_locked(state)
    print(f"Wrapped tabs enabled in {workspace_id}")


def disable():
    workspace_id = os.environ.get("HERDR_WORKSPACE_ID") or snapshot()["focused_workspace_id"]
    with lock_state():
        state = read_state()
        if workspace_id not in state["disabled"]:
            state["disabled"].append(workspace_id)
        write_state(state)
        current = snapshot()
        tab_ids = {tab["tab_id"] for tab in current["tabs"] if tab["workspace_id"] == workspace_id}
        for tab_id in tab_ids:
            pane_id = state["panes"].pop(tab_id, None)
            if pane_id:
                try:
                    request("plugin.pane.close", {"pane_id": pane_id})
                except RuntimeError:
                    pass
        write_state(state)
    print(f"Wrapped tabs disabled in {workspace_id}")


def sync():
    with lock_state():
        sync_locked(read_state())


def is_restored_bar(pane):
    pane_cwd = pane.get("cwd")
    if pane.get("label") != BAR_TITLE or not pane_cwd:
        return False
    cwd = pathlib.Path(pane_cwd).resolve()
    # ponytail: recognize a restored shell at $HOME by its reserved label; use a stable plugin-pane ID when Herdr exposes one.
    return (
        cwd == PLUGIN_ROOT.resolve()
        or cwd == pathlib.Path.home().resolve()
        or cwd.parent == PLUGIN_ROOT.parent and cwd.name.startswith(f"{PLUGIN_ID}-")
    )


def restore():
    with lock_state():
        state = read_state()
        if state["suspended"]:
            return
        current = snapshot()
        layouts = {layout["tab_id"]: layout for layout in current["layouts"]}
        tabs = {tab["tab_id"]: tab for tab in current["tabs"]}
        panes = {pane["pane_id"]: pane for pane in current["panes"]}
        for tab_id, layout in layouts.items():
            tab = tabs.get(tab_id)
            if not tab or tab["workspace_id"] in state["disabled"] or layout.get("zoomed") or len(layout["panes"]) != 2:
                continue
            layout_pane_ids = {item["pane_id"] for item in layout["panes"]}
            restored_bars = [
                panes[pane_id] for pane_id in layout_pane_ids if pane_id in panes
                and is_restored_bar(panes[pane_id])
            ]
            if len(restored_bars) != 1:
                continue
            restored_bar = restored_bars[0]
            target = next(item["pane_id"] for item in layout["panes"] if item["pane_id"] != restored_bar["pane_id"])
            workspace_tabs = [item for item in current["tabs"] if item["workspace_id"] == tab["workspace_id"]]
            pane_id = open_bar(tab_id, target, workspace_tabs, layout)
            request("pane.close", {"pane_id": restored_bar["pane_id"]})
            state["panes"][tab_id] = pane_id
            write_state(state)
        sync_locked(state)


def refresh():
    with lock_state():
        state = read_state()
        state["suspended"] = False
        write_state(state)
        sync_locked(state)


def remove_all():
    with lock_state():
        state = read_state()
        state["suspended"] = True
        write_state(state)
        for pane_id in state["panes"].values():
            try:
                request("plugin.pane.close", {"pane_id": pane_id})
            except RuntimeError:
                pass
        state["panes"] = {}
        write_state(state)
    print("Wrapped tabs removed from all workspaces")


def draw(screen, positions, selected_tab_id, hovered_tab_id, scroll_offset, total_rows):
    screen.erase()
    height, width = screen.getmaxyx()
    for tab_id, label, row, column, _length in positions:
        visible_row = row - scroll_offset
        if visible_row < 0 or visible_row >= height or column >= width:
            continue
        if tab_id == selected_tab_id:
            style = curses.A_REVERSE | curses.A_BOLD
        elif tab_id == hovered_tab_id:
            style = curses.A_UNDERLINE | curses.A_BOLD
        else:
            style = curses.A_DIM
        try:
            screen.addnstr(visible_row, column, label, width - column, style)
        except curses.error:
            pass
    if width > 1 and scroll_offset > 0:
        try:
            screen.addstr(0, width - 1, "↑", curses.A_BOLD)
        except curses.error:
            pass
    if width > 1 and scroll_offset + height < total_rows:
        try:
            screen.addstr(height - 1, width - 1, "↓", curses.A_BOLD)
        except curses.error:
            pass
    screen.refresh()


def parse_input(buffer):
    events = []
    while buffer:
        if buffer.startswith(b"\x1b[<"):
            match = MOUSE_EVENT.match(buffer)
            if match:
                button, column, row, suffix = match.groups()
                events.append(("mouse", (int(button), int(column) - 1, int(row) - 1, suffix)))
                buffer = buffer[match.end():]
                continue
            if len(buffer) < 64:
                break
        if buffer.startswith(b"\x1b["):
            match = next(((sequence, name) for sequence, name in KEY_SEQUENCES.items() if buffer.startswith(sequence)), None)
            if match:
                sequence, name = match
                events.append(("key", name))
                buffer = buffer[len(sequence):]
                continue
            if any(sequence.startswith(buffer) for sequence in (*KEY_SEQUENCES, b"\x1b[<")):
                break
        if buffer[0] == 27:
            buffer = buffer[1:]
            continue
        events.append(("key", chr(buffer[0])))
        buffer = buffer[1:]
    return events, buffer


def view(screen):
    curses.curs_set(0)
    sys.stdout.write("\x1b[?1003h\x1b[?1006h")
    sys.stdout.flush()
    input_fd = sys.stdin.fileno()
    workspace_id = os.environ["HERDR_WORKSPACE_ID"]
    tab_id = os.environ["HERDR_TAB_ID"]
    pane_id = os.environ["HERDR_PANE_ID"]
    chosen = tab_id
    hovered = None
    scroll_offset = 0
    input_buffer = b""
    tabs = []
    positions = []
    total_rows = 0
    last_render = None
    next_refresh = 0
    while True:
        size = os.get_terminal_size(input_fd)
        height, width = screen.getmaxyx()
        if (size.lines, size.columns) != (height, width):
            curses.resizeterm(size.lines, size.columns)
            height, width = screen.getmaxyx()
            next_refresh = 0
        now = time.monotonic()
        if now >= next_refresh:
            try:
                tabs = request("tab.list", {"workspace_id": workspace_id})["tabs"]
                tabs.sort(key=lambda tab: tab["number"])
                positions = place_cells(tab_cells(tabs, width), width)
                total_rows = max((position[2] for position in positions), default=0) + 1
                scroll_offset = min(scroll_offset, max(total_rows - height, 0))
                chosen = chosen if any(tab["tab_id"] == chosen for tab in tabs) else tab_id
                resize_bar(pane_id, tab_id, total_rows)
            except (OSError, RuntimeError, KeyError):
                tabs = []
                positions = []
                total_rows = 0
            next_refresh = now + 1
        render_key = (height, width, tuple((tab["tab_id"], tab["label"], tab["number"]) for tab in tabs), chosen, hovered, scroll_offset)
        if render_key != last_render:
            draw(screen, positions, chosen, hovered, scroll_offset, total_rows)
            last_render = render_key
        ready, _, _ = select.select([input_fd], [], [], max(next_refresh - time.monotonic(), 0))
        if not ready:
            continue
        data = os.read(input_fd, 4096)
        if not data:
            return
        events, input_buffer = parse_input(input_buffer + data)
        for kind, value in events:
            if kind == "mouse":
                button, x, y, suffix = value
                hovered = next((item[0] for item in positions if item[2] == y + scroll_offset and item[3] <= x < item[3] + item[4]), None)
                if button & 64:
                    scroll_offset = max(scroll_offset - 1, 0) if button & 1 == 0 else min(scroll_offset + 1, max(total_rows - height, 0))
                elif button & 3 == 0 and suffix == b"M" and hovered:
                    try:
                        request("tab.focus", {"tab_id": hovered})
                    except (OSError, RuntimeError):
                        pass
                continue
            key = value
            if key in ("left", "right", "h", "l") and tabs:
                ids = [tab["tab_id"] for tab in tabs]
                index = ids.index(chosen) if chosen in ids else 0
                chosen = ids[(index + (1 if key in ("right", "l") else -1)) % len(ids)]
                chosen_row = next((item[2] for item in positions if item[0] == chosen), 0)
                if chosen_row < scroll_offset:
                    scroll_offset = chosen_row
                elif chosen_row >= scroll_offset + height:
                    scroll_offset = chosen_row - height + 1
            elif key in ("up", "k"):
                scroll_offset = max(scroll_offset - 1, 0)
            elif key in ("down", "j"):
                scroll_offset = min(scroll_offset + 1, max(total_rows - height, 0))
            elif key == "page_up":
                scroll_offset = max(scroll_offset - height, 0)
            elif key == "page_down":
                scroll_offset = min(scroll_offset + height, max(total_rows - height, 0))
            elif key in ("\r", "\n") and tabs:
                try:
                    request("tab.focus", {"tab_id": chosen})
                except (OSError, RuntimeError):
                    pass


def main():
    action = sys.argv[1]
    if action == "view":
        try:
            curses.wrapper(view)
        finally:
            sys.stdout.write("\x1b[?1003l\x1b[?1006l")
            sys.stdout.flush()
    else:
        {"enable": enable, "disable": disable, "sync": sync, "restore": restore, "refresh": refresh, "remove-all": remove_all}[action]()


if __name__ == "__main__":
    main()
