import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from auto_annotation_tool.ranking import (
    iter_full_event_rows,
    iter_full_frame_flow_rows,
    iter_full_sample_rows,
    iter_full_thermal_rows,
    iter_full_trace_rows,
    read_mobile_report_bundle,
    read_mobile_report_bundles,
)
from auto_annotation_tool.ranking.mobile_package_experiments import MOBILE_BENCHMARK_REPORT_SCHEMA


def _report_payload(report_id: str = "report-001") -> dict:
    return {
        "schema": MOBILE_BENCHMARK_REPORT_SCHEMA,
        "report_id": report_id,
        "package_id": "pkg-mt-mz",
        "variant_id": "tflite-fp32",
        "measured_at": "2026-08-27T20:00:00Z",
        "device": {"name": "test-device", "android_version": "15"},
        "runtime": "tflite",
        "delegate": "cpu",
        "latency": {"pipeline_p95_ms": 123.4},
        "memory": {"ram_peak_mb": 321.0},
        "quality": {"exact_match": 0.91, "cer": 0.03},
    }


def _csv_rows(columns: tuple[str, ...], total: int) -> str:
    lines = [",".join(columns)]
    for index in range(total):
        values = []
        for column in columns:
            if column.endswith("_id"):
                values.append(f"{column}-{index}")
            elif column.endswith("_ms"):
                values.append(str(index * 10))
            else:
                values.append(str(index))
        lines.append(",".join(values))
    return "\n".join(lines) + "\n"


def _write_report_zip(path: Path, *, total: int = 12000) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("report.json", json.dumps(_report_payload(), ensure_ascii=False))
        archive.writestr("traces.csv", _csv_rows(("frame_id", "timestamp_ms", "status", "text"), total))
        archive.writestr("thermal.csv", _csv_rows(("timestamp_ms", "cpu_c", "battery_c"), total))
        archive.writestr("frame_flow.csv", _csv_rows(("frame_id", "stage", "elapsed_ms"), total))
        archive.writestr(
            "events.jsonl",
            "".join(
                json.dumps({"event_id": index, "kind": "frame", "timestamp_ms": index * 10}) + "\n"
                for index in range(total)
            ),
        )
        archive.writestr("samples/index.csv", _csv_rows(("sample_id", "frame_id", "gt"), total))


class MobileReportFullRowsTests(unittest.TestCase):
    def test_full_zip_sources_are_not_limited_by_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "android-report.alprsession"
            _write_report_zip(path)

            bundle = read_mobile_report_bundle(path, max_trace_rows=5000)

            self.assertEqual(bundle.trace_total, 12000)
            self.assertEqual(len(bundle.trace_rows), 5000)
            self.assertEqual(bundle.thermal_total, 12000)
            self.assertEqual(len(bundle.thermal_rows), 5000)
            self.assertEqual(bundle.frame_flow_total, 12000)
            self.assertEqual(len(bundle.frame_flow_rows), 5000)
            self.assertEqual(bundle.event_total, 12000)
            self.assertEqual(len(bundle.event_rows), 5000)
            self.assertEqual(bundle.sample_total, 12000)
            self.assertEqual(len(bundle.sample_rows), 1000)

            self.assertEqual(sum(1 for _ in iter_full_trace_rows(bundle)), 12000)
            self.assertEqual(sum(1 for _ in iter_full_thermal_rows(bundle)), 12000)
            self.assertEqual(sum(1 for _ in iter_full_frame_flow_rows(bundle)), 12000)
            self.assertEqual(sum(1 for _ in iter_full_event_rows(bundle)), 12000)
            self.assertEqual(sum(1 for _ in iter_full_sample_rows(bundle)), 12000)

    def test_json_file_can_hold_many_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reports.json"
            payload = {
                "reports": [
                    dict(_report_payload("report-a"), traces=[{"frame_id": "a-1"}]),
                    dict(_report_payload("report-b"), traces=[{"frame_id": "b-1"}]),
                    dict(_report_payload("report-c"), traces=[{"frame_id": "c-1"}]),
                ]
            }
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            bundles = read_mobile_report_bundles(path)

            self.assertEqual(len(bundles), 3)
            self.assertEqual([bundle.report.report_id for bundle in bundles], ["report-a", "report-b", "report-c"])
            self.assertEqual(sum(1 for _ in iter_full_trace_rows(path)), 3)


if __name__ == "__main__":
    unittest.main()
