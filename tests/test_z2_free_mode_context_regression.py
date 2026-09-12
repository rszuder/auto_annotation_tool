import ast
import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from auto_annotation_tool.gui import z2_context_runtime as context_runtime
from auto_annotation_tool.gui import z2_main_widgets
from auto_annotation_tool.gui import z2_session_runtime as session_runtime


def _assigned_self_attributes(node):
    names = set()
    for child in ast.walk(node):
        if isinstance(child, (ast.Assign, ast.AnnAssign)):
            targets = (
                child.targets
                if isinstance(child, ast.Assign)
                else [child.target]
            )
            for target in targets:
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                ):
                    names.add(target.attr)
    return names


class Z2FreeModeContextRegressionTests(unittest.TestCase):
    def test_route_choice_widgets_are_not_guarded_by_initial_campaign_context(self):
        source = inspect.getsource(
            z2_main_widgets.create_annotation_widgets
        )
        tree = ast.parse(source)
        function = tree.body[0]

        protected = {
            "workflow_entry_title_lbl",
            "workflow_intro_lbl",
            "workflow_cards_frame",
            "auto_route_card",
            "manual_route_card",
        }

        assigned = _assigned_self_attributes(function)
        self.assertTrue(protected <= assigned)

        for node in ast.walk(function):
            if not isinstance(node, ast.If):
                continue
            test_text = ast.unparse(node.test)
            if "initial_campaign_context" not in test_text:
                continue
            guarded = set()
            for stmt in node.body:
                guarded.update(_assigned_self_attributes(stmt))
            self.assertFalse(
                protected & guarded,
                "Widżety wyboru toru free mode nie mogą być tworzone "
                "warunkowo na podstawie kontekstu istniejącego wyłącznie "
                "podczas inicjalizacji Z2.",
            )

    def test_no_active_project_wins_over_stale_z2_campaign_context(self):
        host = SimpleNamespace(
            app=SimpleNamespace(campaign_free_mode=False),
            _campaign_context_project_name="stary-projekt",
            _campaign_graph_entry_context={"graph_gate_id": "T04"},
        )

        with patch(
            "auto_annotation_tool.campaign_manager.CAMPAIGN."
            "get_active_project_name",
            return_value="",
        ):
            result = session_runtime._is_free_mode_session_context(
                host
            )

        self.assertTrue(result)
        self.assertEqual(
            host._campaign_context_project_name,
            "",
        )
        self.assertEqual(
            host._campaign_graph_entry_context,
            {},
        )

    def test_active_project_still_has_priority_over_free_mode_flag(self):
        host = SimpleNamespace(
            app=SimpleNamespace(campaign_free_mode=True),
            _campaign_context_project_name="",
            _campaign_graph_entry_context={},
        )

        with patch(
            "auto_annotation_tool.campaign_manager.CAMPAIGN."
            "get_active_project_name",
            return_value="projekt-A",
        ):
            result = session_runtime._is_free_mode_session_context(
                host
            )

        self.assertFalse(result)
        self.assertFalse(host.app.campaign_free_mode)

    def test_clear_campaign_context_clears_stale_identity_before_free_snapshot(self):
        host = Mock()
        host._campaign_context_project_name = "stary-projekt"
        host._campaign_graph_entry_context = {
            "graph_gate_id": "T04"
        }
        host._pre_campaign_free_mode_snapshot = {
            "free_mode_screen": "route_choice"
        }
        host.input_dir_var.get.return_value = ""

        observed = {}

        def apply_snapshot(*, session_state, restore_preview):
            observed["project"] = (
                host._campaign_context_project_name
            )
            observed["graph"] = dict(
                host._campaign_graph_entry_context
            )
            observed["state"] = dict(session_state or {})
            observed["restore_preview"] = restore_preview

        host._apply_free_mode_session_snapshot.side_effect = (
            apply_snapshot
        )

        context_runtime.clear_campaign_context(
            host,
            restore_free_mode_preview=False,
        )

        self.assertEqual(observed["project"], "")
        self.assertEqual(observed["graph"], {})
        self.assertEqual(
            observed["state"]["free_mode_screen"],
            "route_choice",
        )
        self.assertFalse(observed["restore_preview"])


if __name__ == "__main__":
    unittest.main()
