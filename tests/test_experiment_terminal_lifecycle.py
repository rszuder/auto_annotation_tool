import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.registry.experiment_service import (
    ExperimentGuardError,
    ExperimentService,
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_READY,
    STATUS_RUNNING,
)
from auto_annotation_tool.registry import RegistryRepository


class ExperimentTerminalLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "Workspace"
        self.repo = RegistryRepository.for_workspace(self.workspace)
        self.repo.initialize()
        self.service = ExperimentService(
            self.workspace,
            repository=self.repo,
        )

    def tearDown(self):
        self.temp.cleanup()

    def _insert_experiment(self, experiment_id, status):
        with self.repo.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO experiments (
                    experiment_id, name, target, mode, status
                ) VALUES (?, 'x', 'plate', 'controlled', ?)
                """,
                (experiment_id, status),
            )

    def test_cancel_marks_ready_experiment_cancelled(self):
        self._insert_experiment("EXP-CANCEL", STATUS_READY)
        self.service.cancel("EXP-CANCEL")
        row = self.repo.get_experiment("EXP-CANCEL")
        self.assertEqual(row["status"], STATUS_CANCELLED)
        self.assertTrue(row["finished_at"])

    def test_fail_marks_running_experiment_failed(self):
        self._insert_experiment("EXP-FAIL", STATUS_RUNNING)
        self.service.fail("EXP-FAIL")
        row = self.repo.get_experiment("EXP-FAIL")
        self.assertEqual(row["status"], STATUS_FAILED)
        self.assertTrue(row["finished_at"])

    def test_completed_experiment_cannot_be_cancelled(self):
        self._insert_experiment("EXP-DONE", "COMPLETED")
        with self.assertRaises(ExperimentGuardError):
            self.service.cancel("EXP-DONE")


if __name__ == "__main__":
    unittest.main()
