import unittest
from unittest.mock import Mock

from auto_annotation_tool.gui.app import AutoAnnotationApp


class Z2MainTabEntryRefreshTests(unittest.TestCase):
    def make_app(self):
        app = AutoAnnotationApp.__new__(AutoAnnotationApp)
        app.root = Mock()
        app.tabs = {}
        return app

    def test_annotation_entry_schedules_workflow_refresh(self):
        app = self.make_app()
        tab = Mock()
        app.tabs["annotation"] = tab

        callbacks = []
        app.root.after_idle.side_effect = callbacks.append

        result = app._schedule_z2_main_tab_entry_refresh("annotation")

        self.assertTrue(result)
        self.assertEqual(len(callbacks), 1)
        tab._refresh_free_mode_workflow_ui.assert_not_called()

        callbacks[0]()
        tab._refresh_free_mode_workflow_ui.assert_called_once_with()

    def test_other_main_tab_does_not_refresh_z2(self):
        app = self.make_app()
        tab = Mock()
        app.tabs["annotation"] = tab

        result = app._schedule_z2_main_tab_entry_refresh("characters")

        self.assertFalse(result)
        app.root.after_idle.assert_not_called()
        tab._refresh_free_mode_workflow_ui.assert_not_called()

    def test_missing_annotation_tab_is_safe(self):
        app = self.make_app()

        result = app._schedule_z2_main_tab_entry_refresh("annotation")

        self.assertFalse(result)
        app.root.after_idle.assert_not_called()


if __name__ == "__main__":
    unittest.main()
