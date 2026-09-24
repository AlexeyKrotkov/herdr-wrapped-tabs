import io
import os
import unittest
from unittest.mock import Mock, patch

import wrapped_tabs


class WrappedTabsViewTest(unittest.TestCase):
    def test_focus_change_selects_active_tab_and_keeps_working_dot(self):
        tabs = [
            {"tab_id": "tab-3", "number": 3, "label": "3", "focused": True, "agent_status": "idle"},
            {"tab_id": "tab-4", "number": 4, "label": "4", "focused": False, "agent_status": "working"},
        ]
        screen = Mock()
        screen.getmaxyx.return_value = (10, 40)
        draws = []

        def tab_list(_method, _params):
            result = {"tabs": [tab.copy() for tab in tabs]}
            tabs[0]["focused"], tabs[1]["focused"] = False, True
            return result

        with (
            patch.dict(os.environ, {"HERDR_WORKSPACE_ID": "workspace", "HERDR_TAB_ID": "tab-3", "HERDR_PANE_ID": "pane"}),
            patch.object(wrapped_tabs, "request", side_effect=tab_list),
            patch.object(wrapped_tabs, "resize_bar"),
            patch.object(wrapped_tabs, "draw", side_effect=lambda _screen, positions, chosen, *_args: draws.append((positions, chosen))),
            patch.object(wrapped_tabs, "select") as select,
            patch.object(wrapped_tabs, "time") as clock,
            patch.object(wrapped_tabs.os, "get_terminal_size", return_value=os.terminal_size((40, 10))),
            patch.object(wrapped_tabs.os, "read", return_value=b""),
            patch.object(wrapped_tabs.sys.stdin, "fileno", return_value=0),
            patch.object(wrapped_tabs.sys, "stdout", new_callable=io.StringIO),
            patch.object(wrapped_tabs.curses, "curs_set"),
            patch.object(wrapped_tabs.curses, "has_colors", return_value=False),
        ):
            clock.monotonic.side_effect = [1, 1, 2, 2]
            select.select.side_effect = [([], [], []), ([0], [], [])]
            wrapped_tabs.view(screen)

        self.assertEqual([chosen for _, chosen in draws], ["tab-3", "tab-4"])
        self.assertIn("●", next(position[1] for position in draws[-1][0] if position[0] == "tab-4"))

    def test_selected_tab_draws_red_dot_without_reversing_its_color(self):
        screen = Mock()
        screen.getmaxyx.return_value = (10, 40)
        positions = wrapped_tabs.place_cells(wrapped_tabs.tab_cells([
            {"tab_id": "tab-4", "number": 4, "label": "4"},
        ], 40, {"tab-4"}), 40)

        wrapped_tabs.draw(screen, positions, "tab-4", None, 0, 1, 123)

        self.assertEqual(screen.addstr.call_args.args[-2:], ("●", 123))


if __name__ == "__main__":
    unittest.main()
