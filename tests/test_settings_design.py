import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import flet as ft

from src.constants import DEFAULT_CONFIG
from src.gui import ValorantApp


def controls(root):
    yield root
    for child in root._get_children():
        yield from controls(child)


def texts(root):
    return [item.value for item in controls(root) if isinstance(item, ft.Text)]


class SettingsDesignTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        self.stats = patch("src.gui.Stats").start().return_value
        store = patch("src.gui.app_state").start()
        store.snapshot.return_value = {"revision": 0, "heartbeat": None}
        patch.object(ValorantApp, "_load_settings", return_value=dict(DEFAULT_CONFIG["table"])).start()
        patch.object(ValorantApp, "_load_feature_settings", return_value=dict(DEFAULT_CONFIG["flags"])).start()
        self.page = Mock(width=1520)
        self.page.window.width = 1520
        self.app = ValorantApp(self.page)
        self.app.render = Mock()
        self.save = patch.object(self.app, "_persist_settings", return_value=True).start()

    def test_categories_wrap_and_do_not_write_config_on_render(self):
        view = self.app._settings_view()
        navigation = view.controls[1]
        self.assertTrue(navigation.wrap)
        self.assertEqual([button.text for button in navigation.controls], ["Отображение", "Матч и запуск", "Уведомления", "О приложении"])
        for category in ("Отображение", "Матч и запуск", "Уведомления", "О приложении"):
            self.app.settings_category = category
            self.app._settings_view()
        self.save.assert_not_called()
        self.stats.clear_data.assert_not_called()

    def test_display_contains_all_existing_options_and_sources(self):
        view = self.app._settings_view()
        switches = [item for item in controls(view) if isinstance(item, ft.Switch)]
        self.assertEqual(len(switches), 10)
        self.assertIn("HS%", texts(view))
        self.assertIn("K/D", texts(view))
        self.assertIn("WR и число игр за текущий акт", texts(view))
        self.assertTrue(any("последний завершённый рейтинговый матч" in value for value in texts(view)))
        self.assertTrue(any("Командные панели" in value for value in texts(view)))
        self.assertEqual(sum(isinstance(item, ft.SegmentedButton) for item in controls(view)), 1)

    def test_category_change_resets_only_settings_scroll(self):
        self.app.scroll_positions = {"settings": 500, "history": 123}
        self.app._settings_view().controls[1].controls[2].on_click(None)
        self.assertEqual(self.app.settings_category, "Уведомления")
        self.assertEqual(self.app.scroll_positions, {"settings": 0, "history": 123})
        self.app.render.assert_called_once()
        self.save.assert_not_called()
        self.assertEqual(sum(isinstance(item, ft.Switch) for item in controls(self.app._settings_view())), 4)

    def test_native_switch_and_card_click_persist_once_each(self):
        card = self.app._toggle_setting_card("table", "kd", "K/D", "Description", ft.Icons.QUERY_STATS_ROUNDED)
        switch = next(item for item in controls(card) if isinstance(item, ft.Switch))
        self.assertFalse(switch.value)
        switch.value = True
        switch.on_change(SimpleNamespace(control=switch))
        self.save.assert_called_once_with({"table": {"kd": True}})
        self.assertTrue(self.app.settings["kd"])
        self.assertIn("ВКЛ", texts(card))
        card.on_click(None)
        self.assertEqual(self.save.call_count, 2)
        self.assertFalse(self.app.settings["kd"])
        self.assertFalse(switch.value)
        self.assertIn("ВЫКЛ", texts(card))

    def test_failed_switch_save_reverts_value_and_label(self):
        self.save.return_value = False
        card = self.app._toggle_setting_card("flags", "notifications", "Messages", "Description", ft.Icons.NOTIFICATIONS_ACTIVE_ROUNDED)
        switch = next(item for item in controls(card) if isinstance(item, ft.Switch))
        initial = self.app.feature_settings["notifications"]
        switch.value = not initial
        switch.on_change(SimpleNamespace(control=switch))
        self.assertEqual(switch.value, initial)
        self.assertEqual(self.app.feature_settings["notifications"], initial)
        self.assertIn("ВКЛ" if initial else "ВЫКЛ", texts(card))

    def test_reset_cancel_does_not_save_or_clear_history(self):
        self.app._confirm_reset_settings(None)
        dialog = self.page.open.call_args.args[0]
        self.assertIn("История матчей не будет удалена", dialog.content.value)
        dialog.actions[0].on_click(None)
        self.save.assert_not_called()
        self.stats.clear_data.assert_not_called()
        self.page.close.assert_called_once_with(dialog)

    def test_reset_confirmation_restores_defaults_not_history(self):
        self.app.settings["kd"] = not DEFAULT_CONFIG["table"]["kd"]
        self.app.history = [{"match_id": "keep"}]
        self.app._confirm_reset_settings(None)
        dialog = self.page.open.call_args.args[0]
        dialog.actions[1].on_click(None)
        self.save.assert_called_once_with({"table": DEFAULT_CONFIG["table"], "flags": DEFAULT_CONFIG["flags"]})
        self.assertEqual(self.app.settings, DEFAULT_CONFIG["table"])
        self.assertEqual(self.app.history, [{"match_id": "keep"}])
        self.stats.clear_data.assert_not_called()
        self.app.render.assert_called_once()

    def test_rank_style_failure_restores_selection(self):
        self.save.return_value = False
        tile = self.app._rank_icon_style_tile()
        segmented = next(item for item in controls(tile) if isinstance(item, ft.SegmentedButton))
        segmented.selected = {"minimal"}
        segmented.on_change(SimpleNamespace(control=segmented))
        self.assertEqual(segmented.selected, {"official"})
        self.assertEqual(self.app.settings["rank_icon_style"], "official")

    def test_notifications_describe_actual_scope(self):
        self.app.settings_category = "Уведомления"
        values = texts(self.app._settings_view())
        self.assertIn("Всплывающие сообщения", values)
        self.assertTrue(any("Системное уведомление" in text and "отдельно" in text for text in values))
        self.assertTrue(any("Не беспокоить" in text for text in values))

    def test_rows_have_no_fixed_height_and_text_can_wrap(self):
        self.page.width = 600
        card = self.app._toggle_setting_card("table", "skin", "Long label " * 10, "Long description " * 10, ft.Icons.AUTO_AWESOME_ROUNDED)
        self.assertIsNone(card.height)
        self.assertEqual(card.col["xs"], 12)
        self.assertTrue(all(item.max_lines is None for item in controls(card) if isinstance(item, ft.Text)))
        self.app.settings_category = "unknown"
        self.app._settings_view()
        self.assertEqual(self.app.settings_category, "Отображение")


if __name__ == "__main__":
    unittest.main()
