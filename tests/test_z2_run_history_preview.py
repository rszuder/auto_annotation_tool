from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from auto_annotation_tool.gui import z2_miniflow_runtime as flow
from auto_annotation_tool.gui import z2_run_history_preview as preview


def test_history_label_contains_total_at_count():
    owner = SimpleNamespace(
        _resolve_safe_annotation_run_dir=lambda path, **kwargs: Path(path),
        _get_run_plate_annotation_counts=Mock(return_value=(7, 12)),
    )
    label = flow._format_manual_review_history_label(
        owner,
        {
            "run_dir": "run_001_20260925_120000",
            "created_at": "2026-09-25T12:00:00",
        },
    )
    assert label == "run_001_20260925_120000 | 2026-09-25 12:00 | AT: 12"


def test_evenly_spaced_sample_covers_entire_run():
    assert preview.select_evenly_spaced(list(range(101)), 5) == [0, 25, 50, 75, 100]


def test_collect_preview_filters_images_without_at(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "annotations.xml").write_text("<annotations/>", encoding="utf-8")
    images = run / "images"
    images.mkdir()

    plate = SimpleNamespace(bbox=(1, 2, 10, 12), polygon=None)
    a = SimpleNamespace(filename="a.jpg")
    b = SimpleNamespace(filename="b.jpg")
    c = SimpleNamespace(filename="c.jpg")

    owner = SimpleNamespace(
        _resolve_safe_annotation_run_dir=lambda path, **kwargs: Path(path),
        _parse_cvat_preview_annotations=Mock(return_value=[a, b, c]),
        _get_plate_detections=lambda ann: [plate] if ann in (a, c) else [],
        _load_annotation_run_manifest=Mock(return_value={}),
        _resolve_run_image_dir_for_annotations=Mock(return_value=images),
        _get_run_plate_annotation_counts=Mock(return_value=(2, 2)),
    )

    result = preview.collect_run_history_preview_items(owner, run)
    assert result["ok"]
    assert result["total_plates"] == 2
    assert [item["filename"] for item in result["items"]] == ["a.jpg", "c.jpg"]


def test_selection_change_enables_preview_and_open_buttons():
    class Button:
        def __init__(self):
            self.state = None
        def configure(self, **kwargs):
            self.state = kwargs.get("state")

    owner = SimpleNamespace(
        manual_history_open_btn=Button(),
        manual_history_preview_btn=Button(),
        _get_selected_manual_review_history_run_dir=lambda: Path("run"),
        _refresh_step2_action_states=Mock(),
        _refresh_free_mode_workflow_ui=Mock(),
        _queue_free_mode_session_save=Mock(),
    )
    flow._on_manual_history_selection_changed(owner)
    assert owner.manual_history_open_btn.state == "normal"
    assert owner.manual_history_preview_btn.state == "normal"
