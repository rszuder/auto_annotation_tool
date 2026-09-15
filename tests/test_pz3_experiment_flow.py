import json
from pathlib import Path
import tempfile
import unittest

from pz3_test_support import PZ3Fixture
from auto_annotation_tool.registry.track_service import EvaluationTrackError
from auto_annotation_tool.registry.experiment_gt_workspace import prepare_gt_workspace, publish_working_gt
from auto_annotation_tool.registry.track_readiness import track_readiness


class PZ3ExperimentFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.fixture = PZ3Fixture(self.temp.name)
        self.service = self.fixture.service
        self.track = self.fixture.track

    def tearDown(self):
        self.temp.cleanup()

    def _audited_pool(self):
        image = self.fixture.image("TEST_001.png", seed=987)
        report = self.fixture.audit.audit_paths(self.track, [image])
        self.service.add_member(self.track, image)
        self.fixture.audit.record_ingested_report(self.track, report, [image])
        return image

    def _draw_gt(self, context):
        import xml.etree.ElementTree as ET
        path = Path(context["annotation_path"])
        tree = ET.parse(path)
        image = tree.getroot().find("image")
        ET.SubElement(image, "polygon", label="plate", points="10,10;80,10;80,40;10,40")
        tree.write(path, encoding="utf-8", xml_declaration=True)
        return path

    def test_required_steps_and_current_after_ingest(self):
        new = self.service.create_draft(name="New", target="plate", purpose="ranking")
        state = self.service.get_preparation_state(new)
        self.assertFalse(state.can_add_images)
        self.assertFalse(state.can_prepare_gt)
        self.assertFalse(state.can_verify)
        self.assertTrue(self.service.get_preparation_state(self.track).can_add_images)
        self._audited_pool()
        state = self.service.get_preparation_state(self.track)
        self.assertTrue(state.audit_current)
        self.assertTrue(state.can_prepare_gt)
        self.assertFalse(state.can_verify)

    def test_gt_requires_current_audit(self):
        image = self.fixture.image("TEST_001.png", seed=987)
        self.service.add_member(self.track, image)
        with self.assertRaises(EvaluationTrackError):
            prepare_gt_workspace(self.service, self.track)

    def test_existing_work_is_opened_without_overwrite(self):
        self._audited_pool()
        first = prepare_gt_workspace(self.service, self.track)
        self.assertFalse(first["gt_existing"])
        path = self._draw_gt(first)
        before = path.read_bytes()
        second = prepare_gt_workspace(self.service, self.track)
        self.assertTrue(second["gt_existing"])
        self.assertEqual(first["annotation_path"], second["annotation_path"])
        self.assertEqual(path.read_bytes(), before)

    def test_publish_verify_and_frozen_contract(self):
        self._audited_pool()
        context = prepare_gt_workspace(self.service, self.track)
        path = self._draw_gt(context)
        publish_working_gt(self.service, self.track, path)
        self.assertTrue(self.service.get_preparation_state(self.track).can_verify)
        self.service.verify(self.track, manual_gt_complete=True)
        self.assertTrue(self.service.get_preparation_state(self.track).can_seal)
        result = self.service.seal(self.track)
        self.assertTrue(result.ok, result.issues)
        track = self.service.get_track(self.track)
        root = self.service.workspace / track["relative_path"]
        manifest = json.loads((root / "track_manifest.json").read_text(encoding="utf-8"))
        contract = manifest["experiment_contract"]
        self.assertEqual({p["model_id"] for p in contract["participants"]}, {"M1", "M2"})
        self.assertEqual(contract["audit"]["status"], "CURRENT")
        self.assertTrue(contract["gt_verification"]["manual_gt_complete"])
        self.fixture.audit.participants_path(self.track).write_text('{"participants": []}', encoding="utf-8")
        self.assertEqual({p.model_id for p in self.fixture.audit.load_participants(self.track)}, {"M1", "M2"})

    def test_audit_change_blocks_gt_and_seal(self):
        self._audited_pool()
        context = prepare_gt_workspace(self.service, self.track)
        publish_working_gt(self.service, self.track, self._draw_gt(context))
        self.service.verify(self.track, manual_gt_complete=True)
        self.fixture.audit.invalidate_track_audit(self.track, reason="test_change")
        self.assertFalse(self.service.get_preparation_state(self.track).can_seal)
        with self.assertRaises(EvaluationTrackError):
            self.service.seal(self.track)

    def test_validation_does_not_require_ranking_audit(self):
        state = track_readiness(
            {"status": "DRAFT", "purpose": "validation", "target": "plate"},
            member_count=1, gt_exists=True,
        )
        self.assertTrue(state.can_prepare_gt)
        self.assertTrue(state.can_verify)

    def _model_paths(self):
        paths = []
        for index, model_id in enumerate(("M1", "M2")):
            path = self.fixture.workspace / f"{model_id}.pt"
            path.write_bytes(model_id.encode())
            self.fixture.repo.upsert_model_location(
                model_id=model_id, sha256=self.service._sha256(path), project_id=None,
                run_id=f"R{index+1}", target="plate", task_type="pose",
                yolo_family="YOLO26", yolo_scale=("n", "s")[index],
                checkpoint_kind="trained_export", provenance_status="complete",
                created_at="2026-09-15T00:00:00", location_key="flow_test",
                relative_path=path.name, external_path=None, is_primary=True,
            )
            paths.append(path)
        return paths

    def _verified(self):
        self._audited_pool()
        context = prepare_gt_workspace(self.service, self.track)
        publish_working_gt(self.service, self.track, self._draw_gt(context))
        self.service.verify(self.track, manual_gt_complete=True)
        return context

    def test_comparison_keeps_frozen_models_and_persists_both_results(self):
        from auto_annotation_tool.gui.pz3_comparison import resolve_comparison
        from auto_annotation_tool.ranking.experiment_bridge import RankingExperimentBridge
        from auto_annotation_tool.registry.experiment_service import ExperimentGuardError

        paths = self._model_paths()
        self._verified()
        self.service.attest_independent_acquisition(self.track, source_pool="synthetic_test_fixture")
        self.service.seal(self.track)
        comparison = resolve_comparison(self.service, self.track)
        self.assertEqual(comparison["model_paths"], [str(path) for path in paths])
        ranking_dir = self.fixture.workspace / "rankings"
        ranking_dir.mkdir()
        bridge = RankingExperimentBridge(workspace_dir=self.fixture.workspace, ranking_dir=ranking_dir)
        with self.assertRaisesRegex(ExperimentGuardError, "pieczęci"):
            bridge.prepare(
                name="wrong participants", target="plate",
                reference_path=comparison["reference_path"], model_paths=paths[:1],
            )
        context = bridge.prepare(
            name="fixture comparison", target="plate",
            reference_path=comparison["reference_path"], model_paths=paths,
        )
        for path in paths:
            bridge.record_result(context, path, {"model_name": path.name, "fixture": True})
        bridge.finish(context)
        rows = self.fixture.repo.list_experiment_results(context.experiment_id)
        self.assertEqual({row["model_id"] for row in rows}, {"M1", "M2"})
        self.assertEqual(context.track_id, self.track)

    def test_failed_seal_write_keeps_verified_and_can_retry(self):
        from unittest.mock import patch

        self._verified()
        real_write = self.service._atomic_json

        def fail_seal(path, payload):
            if path.name == "seal.json":
                raise OSError("fixture disk write failure")
            return real_write(path, payload)

        with patch.object(self.service, "_atomic_json", side_effect=fail_seal):
            with self.assertRaises(OSError):
                self.service.seal(self.track)
        self.assertEqual(self.service.get_track(self.track)["status"], "VERIFIED")
        self.assertFalse(self.service.verify_integrity(self.track).ok)
        self.assertTrue(self.service.seal(self.track).ok)

    def test_existing_registered_gt_is_opened_automatically(self):
        self._audited_pool()
        context = prepare_gt_workspace(self.service, self.track)
        path = self._draw_gt(context)
        saved = publish_working_gt(self.service, self.track, path)
        expected = saved.read_bytes()
        path.unlink()
        reopened = prepare_gt_workspace(self.service, self.track)
        self.assertTrue(reopened["gt_existing"])
        self.assertEqual(Path(reopened["annotation_path"]).read_bytes(), expected)

    def test_changed_member_content_blocks_publishing_old_gt(self):
        self._audited_pool()
        context = prepare_gt_workspace(self.service, self.track)
        path = self._draw_gt(context)
        member = self.service.list_members(self.track)[0]
        self.service.remove_members(self.track, [member["member_index"]])
        changed = self.fixture.image(member["original_name"], seed=654)
        report = self.fixture.audit.audit_paths(self.track, [changed])
        self.service.add_member(self.track, changed)
        self.fixture.audit.record_ingested_report(self.track, report, [changed])
        with self.assertRaisesRegex(EvaluationTrackError, "zmienił"):
            publish_working_gt(self.service, self.track, path)

    def test_partial_preannotation_preserves_working_gt_and_reopens_it(self):
        import xml.etree.ElementTree as ET
        from auto_annotation_tool.registry.experiment_gt_workspace import merge_preannotation_working_copy

        first = self._audited_pool()
        other = self.fixture.image("TEST_002.png", seed=432)
        self.service.add_member(self.track, other)
        report = self.fixture.audit.audit_paths(self.track, [first, other])
        self.fixture.audit.record_ingested_report(self.track, report, [first, other])
        context = prepare_gt_workspace(self.service, self.track)
        working = Path(context["annotation_path"])
        prediction = working.parent.parent / "auto_run" / "annotations.xml"
        prediction.parent.mkdir()
        prediction.write_text(
            '<annotations><image id="0" name="TEST_001.png" width="192" height="128">'
            '<polygon label="plate" points="10,10;80,10;80,40;10,40"/>'
            '</image></annotations>', encoding="utf-8",
        )
        source_bytes = prediction.read_bytes()
        merged = merge_preannotation_working_copy(self.service, self.track, prediction)
        nodes = ET.parse(merged).getroot().findall("image")
        self.assertEqual({node.get("name") for node in nodes}, {"TEST_001.png", "TEST_002.png"})
        self.assertEqual(sum(len(node.findall("polygon")) for node in nodes), 1)
        reopened = prepare_gt_workspace(self.service, self.track)
        self.assertEqual(reopened["annotation_path"], str(merged))
        self.assertEqual(len(ET.parse(merged).getroot().findall(".//polygon")), 1)
        self.assertEqual(prediction.read_bytes(), source_bytes)

    def test_gt_archive_after_member_removal_is_covered_by_seal(self):
        first = self._audited_pool()
        second = self.fixture.image("TEST_002.png", seed=433)
        self.service.add_member(self.track, second)
        report = self.fixture.audit.audit_paths(self.track, [first, second])
        self.fixture.audit.record_ingested_report(self.track, report, [first, second])
        context = prepare_gt_workspace(self.service, self.track)
        publish_working_gt(self.service, self.track, self._draw_gt(context))
        second_member = next(row for row in self.service.list_members(self.track)
                             if row["original_name"] == second.name)
        self.service.remove_members(self.track, [second_member["member_index"]])
        report = self.fixture.audit.audit_paths(self.track, [first])
        self.fixture.audit.record_ingested_report(self.track, report, [first])
        context = prepare_gt_workspace(self.service, self.track)
        publish_working_gt(self.service, self.track, Path(context["annotation_path"]))
        self.service.verify(self.track, manual_gt_complete=True)
        self.assertTrue(self.service.seal(self.track).ok)


if __name__ == "__main__":
    unittest.main()
