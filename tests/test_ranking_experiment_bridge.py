import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from auto_annotation_tool.ranking.experiment_bridge import (
    RankingExperimentBridge,
)
from auto_annotation_tool.registry.experiment_service import (
    ExperimentGuardError,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _Repo:
    def __init__(self, models=None):
        self.models = dict(models or {})
        self.participants = {}
        self.results = {}

    def initialize(self):
        return 1

    def get_model_by_sha256(self, sha):
        return self.models.get(sha)

    def list_experiment_participants(self, experiment_id):
        return list(self.participants.get(experiment_id, ()))

    def list_experiment_results(self, experiment_id):
        return list(self.results.get(experiment_id, ()))


class _TrackService:
    def __init__(self, rows):
        self.rows = list(rows)

    def list_tracks(self, **_kwargs):
        return list(self.rows)


class _ExperimentService:
    def __init__(self, repo):
        self.repo = repo
        self.created = []
        self.started = []
        self.finished = []
        self.cancelled = []
        self.failed = []
        self.recorded = []

    def create(self, **kwargs):
        self.created.append(dict(kwargs))
        experiment_id = "EXP-TEST"
        model_ids = tuple(kwargs["model_ids"])
        self.repo.participants[experiment_id] = [
            {"model_id": model_id}
            for model_id in model_ids
        ]
        return SimpleNamespace(
            experiment_id=experiment_id,
            target=kwargs["target"],
            track_id=kwargs["track_id"],
            mode=kwargs["mode"],
            protocol_sha256="p" * 64,
            track_manifest_sha256="m" * 64,
            track_reference_sha256="r" * 64,
            independence_confirmed=True,
            participants=tuple(
                SimpleNamespace(
                    model_id=model_id,
                    independence_status="PASS",
                )
                for model_id in model_ids
            ),
        )

    def start(self, experiment_id):
        self.started.append(experiment_id)

    def record_result(
        self,
        experiment_id,
        model_id,
        *,
        metrics,
        result_relative_path=None,
    ):
        self.recorded.append(
            (
                experiment_id,
                model_id,
                metrics,
                result_relative_path,
            )
        )
        self.repo.results.setdefault(
            experiment_id,
            [],
        ).append({"model_id": model_id})

    def finish(self, experiment_id):
        self.finished.append(experiment_id)

    def cancel(self, experiment_id):
        self.cancelled.append(experiment_id)

    def fail(self, experiment_id):
        self.failed.append(experiment_id)


class RankingExperimentBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "Workspace"
        self.track_root = (
            self.workspace
            / "10_evaluation_tracks"
            / "plate"
            / "track"
        )
        self.track_root.mkdir(parents=True)
        self.ranking_dir = (
            self.workspace / "7_rankings" / "plates"
        )
        self.ranking_dir.mkdir(parents=True)

        self.model_a = Path(self.temp.name) / "a.pt"
        self.model_b = Path(self.temp.name) / "b.pt"
        self.model_a.write_bytes(b"a-model")
        self.model_b.write_bytes(b"b-model")

        self.repo = _Repo(
            {
                _sha(self.model_a): {
                    "model_id": "MODEL-A",
                    "sha256": _sha(self.model_a),
                    "target": "plate",
                },
                _sha(self.model_b): {
                    "model_id": "MODEL-B",
                    "sha256": _sha(self.model_b),
                    "target": "plate",
                },
            }
        )
        self.track_service = _TrackService(
            [
                {
                    "track_id": "TRK-1",
                    "target": "plate",
                    "status": "SEALED",
                    "relative_path": (
                        self.track_root.relative_to(
                            self.workspace
                        ).as_posix()
                    ),
                    "owner_project_id": None,
                }
            ]
        )
        self.experiments = _ExperimentService(
            self.repo
        )
        self.bridge = RankingExperimentBridge(
            self.workspace,
            ranking_dir=self.ranking_dir,
            repository=self.repo,
            track_service=self.track_service,
            experiment_service=self.experiments,
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_legacy_reference_returns_none(self):
        legacy = Path(self.temp.name) / "legacy"
        legacy.mkdir()
        context = self.bridge.prepare(
            name="legacy",
            target="plate",
            reference_path=legacy,
            model_paths=(self.model_a, self.model_b),
        )
        self.assertIsNone(context)
        self.assertEqual(self.experiments.created, [])

    def test_registered_track_creates_and_starts_experiment(self):
        context = self.bridge.prepare(
            name="controlled",
            target="plate",
            reference_path=self.track_root,
            model_paths=(self.model_a, self.model_b),
            protocol_options={"device": "cpu"},
        )
        self.assertIsNotNone(context)
        self.assertEqual(
            context.experiment_id,
            "EXP-TEST",
        )
        self.assertEqual(
            self.experiments.started,
            ["EXP-TEST"],
        )
        self.assertEqual(
            self.experiments.created[0]["model_ids"],
            ("MODEL-A", "MODEL-B"),
        )
        self.assertEqual(
            self.experiments.created[0]["protocol_options"][
                "adapter_schema"
            ],
            "alpr.ranking_experiment_bridge.v1",
        )

    def test_track_descendant_path_is_resolved(self):
        ground_truth = self.track_root / "ground_truth"
        ground_truth.mkdir()
        context = self.bridge.prepare(
            name="descendant",
            target="plate",
            reference_path=ground_truth,
            model_paths=(self.model_a, self.model_b),
        )
        self.assertEqual(context.track_id, "TRK-1")

    def test_unregistered_path_inside_track_root_is_blocked(self):
        unknown = (
            self.workspace
            / "10_evaluation_tracks"
            / "plate"
            / "unknown"
        )
        unknown.mkdir(parents=True)
        with self.assertRaises(ExperimentGuardError):
            self.bridge.prepare(
                name="unknown",
                target="plate",
                reference_path=unknown,
                model_paths=(self.model_a, self.model_b),
            )

    def test_unregistered_model_is_blocked_for_registered_track(self):
        unknown_model = Path(self.temp.name) / "x.pt"
        unknown_model.write_bytes(b"x")
        with self.assertRaises(ExperimentGuardError):
            self.bridge.prepare(
                name="bad model",
                target="plate",
                reference_path=self.track_root,
                model_paths=(self.model_a, unknown_model),
            )

    def test_entry_metadata_freezes_experiment_identity(self):
        context = self.bridge.prepare(
            name="meta",
            target="plate",
            reference_path=self.track_root,
            model_paths=(self.model_a, self.model_b),
        )
        metadata = self.bridge.entry_metadata(
            context,
            self.model_a,
        )
        self.assertEqual(
            metadata["experiment_id"],
            "EXP-TEST",
        )
        self.assertEqual(
            metadata["model_id"],
            "MODEL-A",
        )
        self.assertEqual(
            metadata["track_id"],
            "TRK-1",
        )
        self.assertEqual(
            metadata["independence_status"],
            "PASS",
        )

    def test_record_result_uses_model_from_frozen_participants(self):
        context = self.bridge.prepare(
            name="record",
            target="plate",
            reference_path=self.track_root,
            model_paths=(self.model_a, self.model_b),
        )
        entry = SimpleNamespace(
            to_dict=lambda: {
                "ranking_score": 72.5,
                "experiment_id": context.experiment_id,
            }
        )
        self.bridge.record_result(
            context,
            self.model_a,
            entry,
        )
        self.assertEqual(
            self.experiments.recorded[0][1],
            "MODEL-A",
        )
        self.assertEqual(
            self.experiments.recorded[0][2]["ranking_entry"][
                "ranking_score"
            ],
            72.5,
        )

    def test_finish_requires_results_for_all_participants(self):
        context = self.bridge.prepare(
            name="finish guard",
            target="plate",
            reference_path=self.track_root,
            model_paths=(self.model_a, self.model_b),
        )
        self.repo.results["EXP-TEST"] = [
            {"model_id": "MODEL-A"}
        ]
        with self.assertRaises(ExperimentGuardError):
            self.bridge.finish(context)
        self.assertEqual(
            self.experiments.failed,
            ["EXP-TEST"],
        )
        self.assertEqual(
            self.experiments.finished,
            [],
        )

    def test_finish_completes_when_all_results_exist(self):
        context = self.bridge.prepare(
            name="finish",
            target="plate",
            reference_path=self.track_root,
            model_paths=(self.model_a, self.model_b),
        )
        self.repo.results["EXP-TEST"] = [
            {"model_id": "MODEL-A"},
            {"model_id": "MODEL-B"},
        ]
        self.bridge.finish(context)
        self.assertEqual(
            self.experiments.finished,
            ["EXP-TEST"],
        )

    def test_cancel_and_fail_delegate_lifecycle(self):
        context = self.bridge.prepare(
            name="lifecycle",
            target="plate",
            reference_path=self.track_root,
            model_paths=(self.model_a, self.model_b),
        )
        self.bridge.cancel(context)
        self.bridge.fail(context)
        self.assertEqual(
            self.experiments.cancelled,
            ["EXP-TEST"],
        )
        self.assertEqual(
            self.experiments.failed,
            ["EXP-TEST"],
        )

    def test_temp_xml_is_outside_sealed_track(self):
        context = self.bridge.prepare(
            name="temp",
            target="plate",
            reference_path=self.track_root,
            model_paths=(self.model_a, self.model_b),
        )
        temp_xml = self.bridge.working_temp_xml_path(
            context
        )
        self.assertFalse(
            str(temp_xml.resolve()).startswith(
                str(self.track_root.resolve())
            )
        )
        self.assertTrue(
            str(temp_xml.resolve()).startswith(
                str(self.ranking_dir.resolve())
            )
        )


if __name__ == "__main__":
    unittest.main()
