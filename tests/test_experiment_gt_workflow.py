import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from auto_annotation_tool.gui.experiment_gt_workflow import (
    apply_pending_experiment_gt_entry,
)


class Value:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class Host:
    def __init__(self):
        self.workflow_route_var = Value("")
        self.manual_entry_mode_var = Value("")
        self.manual_xml_template_var = Value(False)
        self.manual_vehicle_assist_var = Value(True)


class ExperimentGtWorkflowTests(unittest.TestCase):
    def _write_context(self, workspace: Path, track_id: str, mode: str):
        state = workspace / "10_experiments" / "_state"
        state.mkdir(parents=True)
        (state / "active_z2_context.json").write_text(
            json.dumps({"track_id": track_id}),
            encoding="utf-8",
        )
        (state / "pending_gt_entry.json").write_text(
            json.dumps({
                "track_id": track_id,
                "mode": mode,
                "created_at": "x",
            }),
            encoding="utf-8",
        )

    def test_preannotation_selects_auto_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            self._write_context(workspace, "TRK-1", "preannotation")
            host = Host()
            with patch(
                "auto_annotation_tool.gui.experiment_gt_workflow.CONFIG.WORKSPACE_DIR",
                workspace,
            ):
                changed = apply_pending_experiment_gt_entry(host)
            self.assertTrue(changed)
            self.assertEqual(host.workflow_route_var.get(), "auto")
            self.assertEqual(host._experiment_gt_workflow_mode, "preannotation")

    def test_manual_selects_new_manual_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            self._write_context(workspace, "TRK-2", "manual")
            host = Host()
            with patch(
                "auto_annotation_tool.gui.experiment_gt_workflow.CONFIG.WORKSPACE_DIR",
                workspace,
            ):
                changed = apply_pending_experiment_gt_entry(host)
            self.assertTrue(changed)
            self.assertEqual(host.workflow_route_var.get(), "manual")
            self.assertEqual(host.manual_entry_mode_var.get(), "new")
            self.assertTrue(host.manual_xml_template_var.get())
            self.assertFalse(host.manual_vehicle_assist_var.get())


if __name__ == "__main__":
    unittest.main()
