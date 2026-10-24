import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import flet as ft

from src.constants import DEFAULT_CONFIG
from src.gui import ValorantApp


class ScrollStabilityTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch("src.gui.Stats").start()
        store = patch("src.gui.app_state").start()
        store.snapshot.return_value = {"revision": 0, "heartbeat": None}
        patch.object(ValorantApp, "_load_settings", return_value=dict(DEFAULT_CONFIG["table"])).start()
        patch.object(ValorantApp, "_load_feature_settings", return_value=dict(DEFAULT_CONFIG["flags"])).start()
        self.page = Mock(width=1520)
        self.page.window.width = 1520
        self.app = ValorantApp(self.page)
        self.app.selected_view = 4

    def event(self, pixels, event_type="update"):
        return SimpleNamespace(pixels=pixels, event_type=event_type)

    def run_restore(self, during_wait=None):
        self.app._schedule_scroll_restore("settings")
        args = self.page.run_task.call_args.args
        async def sleep(_):
            if during_wait:
                during_wait()
        with patch("src.gui.asyncio.sleep", side_effect=sleep):
            asyncio.run(args[0](*args[1:]))

    def test_same_view_reuses_scroll_container_and_keeps_position(self):
        first = self.app._scrollable_column("settings", [ft.Text("Before")])
        first.on_scroll(self.event(260))
        second = self.app._scrollable_column("settings", [ft.Text("After")], spacing=14)
        self.assertIs(first, second)
        self.assertEqual(second.controls[0].value, "After")
        self.assertEqual(self.app.scroll_positions["settings"], 260)
        self.assertEqual(second.spacing, 14)

    def test_history_listview_is_reused_without_auto_scroll(self):
        self.app.selected_view = 1
        first = self.app._scrollable_column("history", [], list_view=True)
        self.assertIsInstance(first, ft.ListView)
        self.assertFalse(first.auto_scroll)
        self.assertIs(first, self.app._scrollable_column("history", [ft.Text("New")], list_view=True))

    def test_restore_runs_once_not_three_times(self):
        control = self.app._scrollable_column("settings", [])
        control.scroll_to = Mock()
        self.app.scroll_positions["settings"] = 350
        self.run_restore()
        control.scroll_to.assert_called_once_with(offset=350, duration=0)

    def test_user_scroll_cancels_pending_restore_even_at_zero(self):
        for new_offset in (0, 500):
            with self.subTest(offset=new_offset):
                control = self.app._scrollable_column("settings", [])
                control.scroll_to = Mock()
                self.app.scroll_positions["settings"] = 350
                self.run_restore(lambda: control.on_scroll(self.event(new_offset)))
                control.scroll_to.assert_not_called()
                self.assertEqual(self.app.scroll_positions["settings"], new_offset)

    def test_metrics_event_does_not_overwrite_saved_position(self):
        control = self.app._scrollable_column("settings", [])
        control.scroll_to = Mock()
        self.app.scroll_positions["settings"] = 350
        self.run_restore(lambda: control.on_scroll(self.event(0, "metrics")))
        self.assertEqual(self.app.scroll_positions["settings"], 350)
        control.scroll_to.assert_called_once_with(offset=350, duration=0)

    def test_old_restore_cannot_move_new_control(self):
        control = self.app._scrollable_column("settings", [])
        control.scroll_to = Mock()
        self.app.scroll_positions["settings"] = 350
        replacement = Mock()
        self.run_restore(lambda: self.app.scroll_controls.update(settings=replacement))
        control.scroll_to.assert_not_called()
        replacement.scroll_to.assert_not_called()

    def test_newer_restore_invalidates_older_request(self):
        control = self.app._scrollable_column("settings", [])
        control.scroll_to = Mock()
        self.app.scroll_positions["settings"] = 350
        self.run_restore(lambda: self.app._schedule_scroll_restore("settings"))
        control.scroll_to.assert_not_called()

    def test_switching_tabs_cancels_old_restore_and_ignores_hidden_events(self):
        control = self.app._scrollable_column("settings", [])
        control.scroll_to = Mock()
        self.app.scroll_positions["settings"] = 350
        self.run_restore(lambda: setattr(self.app, "selected_view", 1))
        control.scroll_to.assert_not_called()
        control.on_scroll(self.event(0))
        self.assertEqual(self.app.scroll_positions["settings"], 350)

    def test_late_event_from_replaced_control_is_ignored(self):
        old = self.app._scrollable_column("settings", [])
        self.app._set_scroll_context("settings", "new-category")
        current = self.app._scrollable_column("settings", [])
        current.on_scroll(self.event(180))
        old.on_scroll(self.event(0))
        self.assertEqual(self.app.scroll_positions["settings"], 180)

    def test_initial_zero_does_not_schedule_scroll_command(self):
        self.app._scrollable_column("settings", [])
        self.app._schedule_scroll_restore("settings")
        self.page.run_task.assert_not_called()

    def test_background_render_keeps_container_and_does_not_schedule_restore(self):
        self.app.render()
        control = self.app.scroll_controls["settings"]
        wrapper = self.app.view_switcher.content
        view = wrapper.content
        control.on_scroll(self.event(420))
        self.page.run_task.reset_mock()
        self.app.snapshot["status"] = "INGAME"
        self.app.render()
        self.assertIs(self.app.scroll_controls["settings"], control)
        self.assertIs(self.app.view_switcher.content, wrapper)
        self.assertIs(wrapper.content, view)
        self.assertEqual(self.app.scroll_positions["settings"], 420)
        self.assertFalse(any(call.args[0] == self.app._restore_scroll for call in self.page.run_task.call_args_list))
        self.assertEqual(self.app.view_switcher.content.key, "view-4")

    def test_flet_update_does_not_remove_scroll_or_its_ancestors(self):
        self.app.render()
        root = self.app.view_switcher
        added = []
        root._build_add_commands(added_controls=added)
        index = {"page": self.page}
        for number, control in enumerate(added):
            uid = f"test-{number}"
            control._Control__uid = uid
            index[uid] = control
        wrapper = root.content
        view = wrapper.content
        scroll = self.app.scroll_controls["settings"]
        retained = {root.uid, wrapper.uid, view.uid, scroll.uid}
        self.app.snapshot["status"] = "INGAME"
        self.app.render()
        commands, new_controls, removed_controls = [], [], []
        root.build_update_commands(index, commands, new_controls, removed_controls)
        self.assertTrue(retained.isdisjoint(control.uid for control in removed_controls))
        self.assertTrue(all(not retained.intersection(command.values)
                            for command in commands if command.name == "remove"))
        self.assertNotIn(scroll, new_controls)

    def test_same_tab_click_does_not_rebuild(self):
        self.app.render = Mock()
        self.app.change_view(4)
        self.app.render.assert_not_called()

    def test_settings_category_change_has_fresh_scroll_context(self):
        control = self.app._scrollable_column("settings", [])
        control.on_scroll(self.event(400))
        self.app.render = Mock()
        self.app._set_settings_category("Уведомления")
        current = self.app._scrollable_column("settings", [])
        self.assertIsNot(current, control)
        self.assertEqual(self.app.scroll_positions["settings"], 0)
        control.on_scroll(self.event(500))
        self.assertEqual(self.app.scroll_positions["settings"], 0)

    def test_live_drawer_refresh_keeps_scroll_and_does_not_move_background(self):
        player = {"puuid": "p", "name": "Example#EU"}
        self.app.selected_view = 0
        self.app._show_player_card(player)
        control = self.app.scroll_controls["player-detail"]
        wrapper = self.app.player_panel.content
        control.on_scroll(self.event(300))
        self.page.run_task.reset_mock()
        self.app._show_player_card(player | {"kd": 1.5})
        self.assertIs(self.app.scroll_controls["player-detail"], control)
        self.assertIs(self.app.player_panel.content, wrapper)
        self.assertEqual(self.app.scroll_positions["player-detail"], 300)
        self.page.run_task.assert_not_called()
        self.app._close_player_panel()
        self.page.run_task.assert_not_called()
        self.app._show_player_card(player | {"puuid": "different"})
        self.assertIsNot(self.app.scroll_controls["player-detail"], control)
        self.assertEqual(self.app.scroll_positions["player-detail"], 0)

    def test_history_drawer_refresh_keeps_scroll_without_restore_loops(self):
        self.app.selected_view = 1
        match = {"match_id": "saved", "players": {}, "epoch": 0}
        self.app._show_history_match(match)
        control = self.app.scroll_controls["history-detail"]
        control.on_scroll(self.event(500))
        self.page.run_task.reset_mock()
        self.app._show_history_match(match)
        self.assertIs(self.app.scroll_controls["history-detail"], control)
        self.assertEqual(self.app.scroll_positions["history-detail"], 500)
        self.page.run_task.assert_not_called()
        self.app._show_history_match(match | {"match_id": "different"})
        self.assertIsNot(self.app.scroll_controls["history-detail"], control)
        self.assertEqual(self.app.scroll_positions["history-detail"], 0)


if __name__ == "__main__":
    unittest.main()
