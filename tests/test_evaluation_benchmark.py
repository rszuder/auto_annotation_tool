import tempfile
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

import test_pz3_reviewed_sample as sample_support
from auto_annotation_tool.registry.evaluation_benchmark import (
    benchmark_groups,
    ensure_benchmark_for_track,
    materialize_benchmark_subset,
    resolve_benchmark_subset,
)
from auto_annotation_tool.registry.sample_labels import SampleLabels
from auto_annotation_tool.ranking.benchmark_metrics import (
    evaluate_benchmark_group_metrics,
)


class EvaluationBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.case = sample_support.RawSampleSelectionTests()
        self.case.setUp()
        self.addCleanup(self.case.tearDown)

    def _sealed_case_with_labels(self):
        selected = set(self.case.keep)
        labels = SampleLabels(selected)
        night = labels.add("Noc")
        night_members = set(sorted(selected)[:2])
        labels.assign(night_members, night)
        self.case.commit(sample_labels=labels.payload(self.case.f.track))
        self.case.make_final_gt()
        self.case.f.service.verify(self.case.f.track, manual_gt_complete=True)
        sealed = self.case.f.service.seal(self.case.f.track)
        self.assertTrue(sealed.ok, sealed.issues)
        return night, night_members

    def test_sealed_track_publishes_reusable_benchmark_without_copying_payload(self):
        night, night_members = self._sealed_case_with_labels()
        benchmark = ensure_benchmark_for_track(
            self.case.f.service,
            self.case.f.track,
        )
        self.assertTrue(benchmark["benchmark_id"].startswith("BENCH-"))
        self.assertEqual(benchmark["member_count"], 6)

        manifest = (
            self.case.f.service.workspace
            / "10_experiments"
            / "benchmarks"
            / benchmark["benchmark_id"]
            / "benchmark.json"
        )
        self.assertTrue(manifest.is_file())
        self.assertFalse((manifest.parent / "images").exists())
        self.assertFalse((manifest.parent / "annotations.xml").exists())

        groups = {row["group_id"]: row for row in benchmark_groups(benchmark)}
        self.assertEqual(groups["ALL"]["count"], 6)
        self.assertEqual(groups["LABEL:" + night]["count"], 2)
        self.assertEqual(groups["UNLABELED"]["count"], 4)
        self.assertEqual(set(groups["LABEL:" + night]["sha256"]), night_members)

    def test_subset_materialization_filters_gt_and_is_stable(self):
        night, night_members = self._sealed_case_with_labels()
        benchmark = ensure_benchmark_for_track(self.case.f.service, self.case.f.track)
        subset = resolve_benchmark_subset(benchmark, label_ids=[night])
        self.assertEqual(set(subset["selected_sha256"]), night_members)
        self.assertEqual(subset["count"], 2)

        view = materialize_benchmark_subset(
            self.case.f.service,
            benchmark,
            label_ids=[night],
        )
        self.assertEqual(len(list(Path(view["images_dir"]).iterdir())), 2)
        self.assertEqual(
            len(ET.parse(view["xml_path"]).getroot().findall("image")),
            2,
        )

        second = materialize_benchmark_subset(
            self.case.f.service,
            benchmark,
            label_ids=[night],
        )
        self.assertEqual(second["subset_fingerprint"], view["subset_fingerprint"])
        self.assertEqual(second["reference_path"], view["reference_path"])

    def test_group_metrics_are_separate(self):
        root = Path(tempfile.mkdtemp())
        gt = root / "gt.xml"
        pred = root / "pred.xml"
        gt.write_text(
            """<annotations>
            <image id="0" name="night.jpg" width="100" height="50">
              <polygon label="plate" points="10,10;80,10;80,40;10,40"/>
            </image>
            <image id="1" name="plain.jpg" width="100" height="50">
              <polygon label="plate" points="10,10;80,10;80,40;10,40"/>
            </image>
            </annotations>""",
            encoding="utf-8",
        )
        pred.write_text(
            """<annotations>
            <image id="0" name="night.jpg" width="100" height="50">
              <polygon label="plate" points="10,10;80,10;80,40;10,40">
                <attribute name="corner_source">pose</attribute>
                <attribute name="corner_order">tl_tr_br_bl</attribute>
              </polygon>
            </image>
            <image id="1" name="plain.jpg" width="100" height="50"/>
            </annotations>""",
            encoding="utf-8",
        )
        benchmark = {
            "benchmark_id": "BENCH-TEST",
            "fingerprint": "f" * 64,
            "labels": [{"id": "L-NIGHT", "name": "Noc"}],
            "members": [
                {"original_name": "night.jpg", "sha256": "a" * 64,
                 "label_id": "L-NIGHT", "label_name": "Noc"},
                {"original_name": "plain.jpg", "sha256": "b" * 64,
                 "label_id": "", "label_name": ""},
            ],
        }
        result = evaluate_benchmark_group_metrics(pred, gt, benchmark)
        by = result["by_group"]
        self.assertGreater(by["LABEL:L-NIGHT"]["f1"], 99.0)
        self.assertEqual(by["LABEL:L-NIGHT"]["sample_count"], 1)
        self.assertEqual(by["UNLABELED"]["sample_count"], 1)
        self.assertLess(by["UNLABELED"]["recall"], 1.0)
        self.assertEqual(by["ALL"]["sample_count"], 2)


if __name__ == "__main__":
    unittest.main()
